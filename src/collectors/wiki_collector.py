"""
Wikipedia 数据采集器

通过 MediaWiki API 获取化学物质信息：
- 中文/英文名称和别名
- 工业制备/生产工艺章节
- Infobox 中的物性数据
- 化学反应方程式
- 安全性/危险性描述
"""
import re
from typing import Optional, Dict, Any

import httpx
from loguru import logger

from .base import BaseCollector


class WikipediaCollector(BaseCollector):
    """Wikipedia 采集器（中英文）"""

    source_name = "wikipedia"
    reliability = "medium"

    ZH_API = "https://zh.wikipedia.org/w/api.php"
    EN_API = "https://en.wikipedia.org/w/api.php"

    # 中文维基中化学物质相关的章节标题
    ZH_CHEM_SECTIONS = [
        "制备", "生产", "工业制备", "工业制法", "制造", "合成",
        "化学性质", "物理性质", "安全性", "危险性", "用途",
        "化学反应", "反应",
    ]

    # 英文维基中化学物质相关的章节标题
    EN_CHEM_SECTIONS = [
        "Preparation", "Production", "Industrial production",
        "Synthesis", "Manufacturing", "Reactions",
        "Chemical properties", "Physical properties",
        "Safety", "Hazards", "Uses", "Applications",
    ]

    async def fetch_by_cas(self, cas: str) -> Optional[Dict[str, Any]]:
        """Wikipedia 按 CAS 查询不直接支持，返回 None"""
        # Wikipedia 通常不直接支持 CAS 号查询
        # 由 collect() 方法回退到名称查询
        return None

    async def fetch_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """按名称搜索 Wikipedia（先英文后中文）"""
        async with httpx.AsyncClient(verify=False) as client:
            # 先尝试英文
            en_result = await self._fetch_wiki(client, name, "en")
            # 再尝试中文
            zh_result = await self._fetch_wiki(client, name, "zh")

            if not en_result and not zh_result:
                return None

            return {
                "en_wiki": en_result,
                "zh_wiki": zh_result,
                "merged": self._merge_results(en_result, zh_result),
            }

    async def fetch_by_names(self, name_en: str = "", name_cn: str = "") -> Optional[Dict[str, Any]]:
        """分别用中英文名称获取 Wikipedia 内容"""
        async with httpx.AsyncClient(verify=False) as client:
            en_result = None
            zh_result = None

            if name_en:
                en_result = await self._fetch_wiki(client, name_en, "en")
            if name_cn:
                zh_result = await self._fetch_wiki(client, name_cn, "zh")
            # 如果中文名失败，尝试用英文名查中文维基
            if not zh_result and name_en:
                zh_result = await self._fetch_wiki(client, name_en, "zh")

            if not en_result and not zh_result:
                return None

            return {
                "en_wiki": en_result,
                "zh_wiki": zh_result,
                "merged": self._merge_results(en_result, zh_result),
            }

    async def _fetch_wiki(self, client: httpx.AsyncClient, title: str, lang: str) -> Optional[dict]:
        """获取指定语言维基百科页面内容"""
        api_url = self.EN_API if lang == "en" else self.ZH_API

        # Step 1: 搜索正确的页面标题
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": title,
            "format": "json",
            "srlimit": 3,
        }
        search_data = await self._get_json(client, api_url, search_params)
        if not search_data:
            return None

        search_results = search_data.get("query", {}).get("search", [])
        if not search_results:
            logger.debug(f"[Wiki:{lang}] 未找到页面: {title}")
            return None

        # 使用第一个搜索结果
        page_title = search_results[0]["title"]

        # Step 2: 获取页面摘要和 infobox
        summary_params = {
            "action": "query",
            "prop": "extracts|pageimages|info",
            "exintro": 0,
            "explaintext": 1,
            "exsectionformat": "plain",
            "titles": page_title,
            "format": "json",
            "redirects": 1,
        }
        summary_data = await self._get_json(client, api_url, summary_params)
        if not summary_data:
            return None

        pages = summary_data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})

        extract = page.get("extract", "")

        # Step 3: 获取页面 wikitext（用于解析 infobox 和反应方程式）
        wikitext_params = {
            "action": "parse",
            "page": page_title,
            "prop": "wikitext",
            "format": "json",
        }
        wikitext_data = await self._get_json(client, api_url, wikitext_params)
        wikitext = ""
        if wikitext_data:
            wikitext = wikitext_data.get("parse", {}).get("wikitext", {}).get("*", "")

        # Step 4: 解析内容
        sections = self._extract_sections(extract if extract else "", lang)
        infobox = self._parse_infobox(wikitext)
        reactions = self._extract_reactions(wikitext)
        names = self._extract_aliases(page_title, wikitext)

        return {
            "page_title": page_title,
            "language": lang,
            "page_id": page.get("pageid"),
            "extract": extract[:5000] if extract else "",  # 限制长度
            "sections": sections,
            "infobox": infobox,
            "reactions": reactions,
            "aliases": names,
        }

    def _extract_sections(self, text: str, lang: str) -> dict[str, str]:
        """从维基百科纯文本中提取化学相关章节"""
        sections = {}
        target_sections = self.ZH_CHEM_SECTIONS if lang == "zh" else self.EN_CHEM_SECTIONS

        # Wikipedia extract 中的章节以 "== Section ==" 或 "\nSection\n" 标记
        # 简易分割
        lines = text.split("\n")
        current_section = "_intro"
        current_text = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 检测章节标题（纯文本导出中章节标题通常是单独一行且较短）
            is_heading = (
                (len(line) < 80 and
                 any(line.startswith(kw) or line == kw for kw in target_sections if len(line) < 80))
            )
            if is_heading:
                if current_text:
                    sections[current_section] = "\n".join(current_text)
                current_section = line
                current_text = []
            else:
                current_text.append(line)

        if current_text:
            sections[current_section] = "\n".join(current_text)

        return sections

    def _parse_infobox(self, wikitext: str) -> dict:
        """解析 Wikipedia infobox（从 wikitext 中提取 {{chembox ...}} 或 {{infobox chemical ...}}）"""
        infobox = {}

        # 查找 chembox 或 infobox 模板
        infobox_patterns = [
            r'\{\{(?:[Cc]hembox|[Ii]nfobox\s+chemical|[Ii]nfobox\s+element)\s*\n?(.*?)\}\}',
        ]

        for pattern in infobox_patterns:
            match = re.search(pattern, wikitext, re.DOTALL)
            if match:
                content = match.group(1)
                # 解析字段: | FieldName = Value
                field_pattern = r'\|\s*([A-Za-z0-9_]+)\s*=\s*(.*?)(?=\n\||\n\}|\Z)'
                for fm in re.finditer(field_pattern, content, re.DOTALL):
                    key = fm.group(1).strip()
                    value = fm.group(2).strip()
                    # 清理 wiki 标记
                    value = re.sub(r'\{\{[^{}]*\}\}', '', value)   # 移除嵌套模板
                    value = re.sub(r'\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]', r'\1', value)  # 移除 wiki 链接
                    value = re.sub(r'<[^>]+>', '', value)          # 移除 HTML 标签
                    value = re.sub(r"'''?", '', value)              # 移除粗斜体标记
                    value = value.strip()
                    if value:
                        infobox[key] = value
                break

        return infobox

    def _extract_reactions(self, wikitext: str) -> list[dict]:
        """从 wikitext 中提取化学反应方程式"""
        reactions = []

        # 查找 <chem> 或 <ce> 标签
        chem_pattern = r'<(?:chem|ce)>(.*?)</(?:chem|ce)>'
        for match in re.finditer(chem_pattern, wikitext):
            eq = match.group(1).strip()
            if eq and len(eq) > 3:
                reactions.append({
                    "equation": eq,
                    "format": "mhchem",
                })

        # 也查找带有 → 或 ⇌ 标记的文本行（可能是反应方程式）
        arrow_pattern = r'([\w\s\+\-\(\)\[\]]+(?:→|⇌|<=>|⟶|⟷)[\w\s\+\-\(\)\[\]]+)'
        for match in re.finditer(arrow_pattern, wikitext):
            eq = match.group(1).strip()
            if eq and len(eq) > 5:
                # 检查是否和 chem 标签重复
                if not any(r["equation"] == eq for r in reactions):
                    reactions.append({
                        "equation": eq,
                        "format": "plain_text",
                    })

        return reactions

    def _extract_aliases(self, page_title: str, wikitext: str) -> list[dict]:
        """提取化学物质的别名"""
        aliases = [{"name": page_title, "type": "page_title"}]

        # 从 chembox 中提取 IUPACName, OtherNames 等
        name_fields = ["IUPACName", "OtherNames", "SystematicName", "PIN"]
        for field in name_fields:
            pattern = rf'\|\s*{field}\s*=\s*(.+?)(?=\n\||\n\}|\Z)'
            match = re.search(pattern, wikitext, re.DOTALL)
            if match:
                value = match.group(1).strip()
                # 清理
                value = re.sub(r'\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]', r'\1', value)
                value = re.sub(r'<[^>]+>', '', value)
                value = value.replace("{{plainlist|", "").replace("{{unbulleted list|", "")
                value = value.replace("}}", "").replace("* ", "").strip()
                for name_part in value.split("\n"):
                    name_part = name_part.strip()
                    if name_part and name_part != page_title:
                        aliases.append({
                            "name": name_part,
                            "type": field.lower(),
                        })

        return aliases

    def _merge_results(self, en: dict, zh: dict) -> dict:
        """合并中英文 Wikipedia 结果"""
        merged = {}

        # 优先用中文名称
        if zh:
            merged["name_cn"] = zh.get("page_title", "")
            merged["zh_sections"] = zh.get("sections", {})
            merged["zh_infobox"] = zh.get("infobox", {})

        if en:
            merged["name_en"] = en.get("page_title", "")
            merged["en_sections"] = en.get("sections", {})
            merged["en_infobox"] = en.get("infobox", {})
            merged["reactions"] = en.get("reactions", [])

        if zh and zh.get("reactions"):
            existing = {r["equation"] for r in merged.get("reactions", [])}
            for r in zh["reactions"]:
                if r["equation"] not in existing:
                    merged.setdefault("reactions", []).append(r)

        return merged
