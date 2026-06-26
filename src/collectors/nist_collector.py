"""
NIST Chemistry WebBook 数据采集器

获取热力学数据：生成焓、熵、热容、反应焓变等。
NIST 是热力学数据的权威来源。

API: https://webbook.nist.gov/cgi/cbook.cgi?ID=C{cas}&Units=SI
解析 HTML 页面中的热化学数据表格。
"""
import re
from typing import Optional, Dict, Any

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from .base import BaseCollector


class NistCollector(BaseCollector):
    """NIST Chemistry WebBook 采集器"""

    source_name = "nist"
    reliability = "high"

    BASE_URL = "https://webbook.nist.gov/cgi/cbook.cgi"

    async def fetch_by_cas(self, cas: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(verify=False) as client:
            return await self._fetch_thermo_data(client, cas)

    async def fetch_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(verify=False) as client:
            # NIST 支持名称查询
            url = f"{self.BASE_URL}?Name={name}&Units=SI&Mask=FFFF"
            html = await self._get(client, url)
            if html:
                return self._parse_html(html)
        return None

    async def _fetch_thermo_data(self, client: httpx.AsyncClient, cas: str) -> Optional[Dict[str, Any]]:
        """
        用 CAS 号获取 NIST 热力学数据。
        URL: ?ID=C{cas}&Units=SI&Mask=FFFF
        """
        # Mask=FFFF 获取全部热化学数据
        url = f"{self.BASE_URL}?ID=C{cas}&Units=SI&Mask=FFFF"
        html = await self._get(client, url)
        if html:
            # 检查是否重定向到具体物质页面
            if "Name" in html[:500] or "Formula" in html[:500]:
                return self._parse_html(html)
            else:
                logger.debug(f"[NIST] CAS {cas} 查询结果可能为空")
        return None

    def _parse_html(self, html: str) -> dict:
        """解析 NIST HTML 页面中的热力学数据"""
        soup = BeautifulSoup(html, "lxml")
        result = {
            "identifiers": {},
            "gas_phase_thermochemistry": [],
            "condensed_phase_thermochemistry": [],
            "reaction_thermochemistry": [],
            "phase_change_data": [],
        }

        # 提取标识信息
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            result["identifiers"]["page_title"] = title_text

        # 查找所有 <h2> 标题
        for h2 in soup.find_all("h2"):
            heading = h2.get_text(strip=True)

            if "Gas phase thermochemistry" in heading:
                table = self._find_next_table(h2)
                if table:
                    result["gas_phase_thermochemistry"] = self._parse_thermo_table(table)

            elif "Condensed phase thermochemistry" in heading:
                table = self._find_next_table(h2)
                if table:
                    result["condensed_phase_thermochemistry"] = self._parse_thermo_table(table)

            elif "Reaction thermochemistry" in heading:
                table = self._find_next_table(h2)
                if table:
                    result["reaction_thermochemistry"] = self._parse_reaction_table(table)

            elif "Phase change data" in heading:
                table = self._find_next_table(h2)
                if table:
                    result["phase_change_data"] = self._parse_phase_table(table)

        return result

    def _find_next_table(self, h2_tag):
        """查找 h2 标签之后最近的 <table>"""
        current = h2_tag.find_next_sibling()
        while current:
            if current.name == "table":
                return current
            if current.name == "h2":
                return None
            current = current.find_next_sibling()
        return None

    def _parse_thermo_table(self, table) -> list[dict]:
        """解析热力学数据表格

        NIST 表格格式通常为：
        | Quantity | Value | Units | Method | Reference | Comment |
        | ΔfH°gas  | -45.9 | kJ/mol | ...    | ...       | ...     |
        """
        results = []
        rows = table.find_all("tr")
        headers = []
        for th in rows[0].find_all("th") if rows else []:
            headers.append(th.get_text(strip=True).lower())

        for row in rows[1:]:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            quantity = cols[0].get_text(strip=True) if len(cols) > 0 else ""
            value_str = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            unit = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            # 解析数值
            value = _parse_scientific(value_str)

            data_type = self._classify_quantity(quantity)
            if data_type:
                entry = {
                    "data_type": data_type,
                    "raw_quantity": quantity,
                    "value": value,
                    "unit": unit,
                    "source": "nist",
                }
                # 方法/参考文献
                if len(cols) > 3:
                    entry["method"] = cols[3].get_text(strip=True)
                if len(cols) > 4:
                    entry["reference"] = cols[4].get_text(strip=True)
                results.append(entry)

        return results

    def _parse_reaction_table(self, table) -> list[dict]:
        """解析反应热化学数据"""
        results = []
        rows = table.find_all("tr")
        for row in rows[1:]:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            # NIST 反应表格按行组织
            reaction_text = cols[0].get_text(strip=True) if len(cols) > 0 else ""
            value_str = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            unit = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            value = _parse_scientific(value_str)

            results.append({
                "reaction": reaction_text,
                "data_type": self._classify_quantity(reaction_text),
                "value": value,
                "unit": unit,
                "source": "nist",
            })

        return results

    def _parse_phase_table(self, table) -> list[dict]:
        """解析相变数据（沸点、熔点等）"""
        results = []
        rows = table.find_all("tr")
        for row in rows[1:]:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            quantity = cols[0].get_text(strip=True) if len(cols) > 0 else ""
            value_str = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            unit = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            value = _parse_scientific(value_str)
            ptype = self._classify_quantity(quantity)

            results.append({
                "property_type": ptype or quantity,
                "value": value,
                "unit": unit,
                "source": "nist",
            })

        return results

    def _classify_quantity(self, quantity: str) -> str | None:
        """将 NIST 的量名称映射到标准 data_type"""
        q = quantity.lower()
        if "enthalpy of formation" in q or "δfh°" in q or "δfh" in q:
            return "enthalpy_of_formation"
        if "enthalpy of combustion" in q or "δch°" in q or "δch" in q:
            return "enthalpy_of_combustion"
        if "entropy" in q or "s°" in q:
            return "entropy"
        if "heat capacity" in q or "cp" in q:
            return "heat_capacity"
        if "gibbs" in q or "δfg°" in q or "δfg" in q:
            return "gibbs_free_energy"
        if "boiling" in q or "tboil" in q:
            return "boiling_point"
        if "melting" in q or "tfus" in q or "freezing" in q:
            return "melting_point"
        if "triple point" in q:
            return "triple_point"
        if "critical" in q:
            return "critical_point"
        if "vapor pressure" in q or "vapour pressure" in q:
            return "vapor_pressure"
        if "sublimation" in q:
            return "enthalpy_of_sublimation"
        if "fusion" in q:
            return "enthalpy_of_fusion"
        if "vaporization" in q:
            return "enthalpy_of_vaporization"
        return None


def _parse_scientific(val_str: str) -> float | None:
    """解析科学记数法字符串"""
    if not val_str:
        return None
    cleaned = val_str.replace("±", " ").split()[0].strip()  # 去掉不确定度
    try:
        return float(cleaned)
    except ValueError:
        return None
