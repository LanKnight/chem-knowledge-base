"""
数据采集器基类

定义所有采集器的统一接口：通过 CAS 号或名称获取化学物质数据。
"""
import asyncio
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any

import httpx
from loguru import logger


@dataclass
class CollectorStats:
    """采集器统计信息"""
    success: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.success + self.failed + self.skipped

    def log_summary(self):
        logger.info(f"采集完成: 成功={self.success}, 失败={self.failed}, 跳过={self.skipped}, 总计={self.total}")
        if self.errors:
            logger.warning(f"错误列表: {self.errors}")


class RateLimiter:
    """简单的令牌桶速率限制器"""

    def __init__(self, rate: float, burst: int = 5):
        self.rate = rate          # 每秒请求数
        self.burst = burst
        self.tokens = burst
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time + 0.05)  # 加少量抖动
                self.tokens = 0
            else:
                self.tokens -= 1


class BaseCollector(ABC):
    """化学数据采集器抽象基类"""

    source_name: str = "base"       # 子类覆盖
    source_id: str = ""             # 对应 data_sources 表 ID（占位）
    reliability: str = "medium"     # high/medium/low

    def __init__(self, config: dict, output_dir: str = "./data/substances"):
        self.config = config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stats = CollectorStats()

        source_cfg = config.get("sources", {}).get(self.source_name, {})
        self.rate_limiter = RateLimiter(rate=source_cfg.get("rate_limit", 2))
        self.timeout = source_cfg.get("timeout", 30)
        self.retry_max = source_cfg.get("retry_max", 3)
        self.user_agent = source_cfg.get(
            "user_agent",
            "HunanRaiweiChemDB/1.0 (research)"
        )

    # ---- 抽象方法（子类必须实现） ----

    @abstractmethod
    async def fetch_by_cas(self, cas: str) -> Optional[Dict[str, Any]]:
        """通过 CAS 号获取数据"""
        ...

    @abstractmethod
    async def fetch_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """通过名称获取数据"""
        ...

    # ---- 辅助方法 ----

    async def _get(self, client: httpx.AsyncClient, url: str, params: dict = None) -> Optional[str]:
        """带速率限制和重试的 HTTP GET"""
        for attempt in range(self.retry_max):
            try:
                await self.rate_limiter.acquire()
                resp = await client.get(
                    url, params=params,
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout,
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 404:
                    logger.debug(f"[{self.source_name}] 404 Not Found: {url}")
                    return None
                elif resp.status_code == 429:
                    wait = min(2 ** attempt, 30)
                    logger.warning(f"[{self.source_name}] 429 限流, 等待 {wait}s")
                    await asyncio.sleep(wait)
                else:
                    logger.warning(f"[{self.source_name}] HTTP {resp.status_code}: {url}")
                    if attempt < self.retry_max - 1:
                        await asyncio.sleep(1)
            except httpx.TimeoutException:
                logger.warning(f"[{self.source_name}] 超时 (attempt {attempt+1}): {url}")
            except Exception as e:
                logger.error(f"[{self.source_name}] 请求异常: {e}")
                if attempt < self.retry_max - 1:
                    await asyncio.sleep(1)
        return None

    async def _get_json(self, client: httpx.AsyncClient, url: str, params: dict = None) -> Optional[dict]:
        """HTTP GET 并解析 JSON"""
        text = await self._get(client, url, params)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                logger.error(f"[{self.source_name}] JSON 解析失败: {e}")
        return None

    def save_data(self, cas: str, data: Dict[str, Any]) -> Path:
        """保存采集结果到 JSON 文件"""
        filepath = self.output_dir / f"{cas.replace('-', '_')}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[{self.source_name}] 数据已保存: {filepath}")
        return filepath

    def load_existing(self, cas: str) -> Optional[Dict[str, Any]]:
        """加载已保存的采集数据（避免重复采集）"""
        filepath = self.output_dir / f"{cas.replace('-', '_')}.json"
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    async def collect(self, cas: str, name_cn: str = "", name_en: str = "") -> Optional[Dict[str, Any]]:
        """
        采集单个物质的完整数据流程：
        1. 先检查是否已有缓存数据
        2. 通过 CAS 号采集
        3. 失败则通过名称采集
        """
        # 检查缓存
        existing = self.load_existing(cas)
        if existing:
            logger.info(f"[{self.source_name}] {cas} 已有缓存数据，跳过")
            self.stats.skipped += 1
            return existing

        try:
            async with httpx.AsyncClient(verify=False) as client:
                result = await self.fetch_by_cas(cas)
                if not result and (name_en or name_cn):
                    logger.info(f"[{self.source_name}] CAS 查询失败，尝试名称查询: {name_en or name_cn}")
                    result = await self.fetch_by_name(name_en or name_cn)
                    if not result and name_cn:
                        result = await self.fetch_by_name(name_cn)

                if result:
                    # 注入来源元信息
                    result["_meta"] = {
                        "source": self.source_name,
                        "reliability": self.reliability,
                        "cas": cas,
                        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                    self.save_data(cas, result)
                    self.stats.success += 1
                    return result
                else:
                    logger.warning(f"[{self.source_name}] 未找到 {cas} ({name_cn}) 的数据")
                    self.stats.failed += 1
                    return None
        except Exception as e:
            logger.error(f"[{self.source_name}] 采集异常 {cas}: {e}")
            self.stats.errors.append(f"{cas}: {str(e)}")
            self.stats.failed += 1
            return None

    async def collect_batch(self, substances: list[dict], concurrency: int = 3) -> list[Optional[dict]]:
        """批量采集（并发控制）"""
        sem = asyncio.Semaphore(concurrency)

        async def _collect_one(sub: dict):
            async with sem:
                return await self.collect(
                    cas=sub["cas_number"],
                    name_cn=sub.get("name_cn", ""),
                    name_en=sub.get("name_en", ""),
                )

        tasks = [_collect_one(s) for s in substances]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        cleaned = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"批量采集异常 [{substances[i].get('cas_number', '?')}]: {r}")
                cleaned.append(None)
            else:
                cleaned.append(r)

        self.stats.log_summary()
        return cleaned
