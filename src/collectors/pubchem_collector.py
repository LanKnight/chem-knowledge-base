"""
PubChem 数据采集器

通过 PubChem PUG REST API 获取化学物质数据：
- 基本标识（CAS→CID→分子式/SMILES/InChI/分子量/名称）
- 理化属性（密度/熔沸点/蒸气压/溶解度/LogP 等）
- 安全性数据（GHS 分类、毒性、H/P 代码、NFPA 等）
"""
from typing import Optional, Dict, Any

import httpx
from loguru import logger

from .base import BaseCollector


class PubChemCollector(BaseCollector):
    """PubChem 数据采集器"""

    source_name = "pubchem"
    reliability = "high"

    BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

    # PubChem 属性列表（一次性获取）
    PROPERTIES = (
        "MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,"
        "InChI,InChIKey,IUPACName,Title,XLogP,ExactMass,MonoisotopicMass,"
        "Charge,Complexity,HBondDonorCount,HBondAcceptorCount,"
        "RotatableBondCount,TPSA,HeavyAtomCount"
    )

    async def fetch_by_cas(self, cas: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(verify=False) as client:
            cid = await self._cas_to_cid(client, cas)
            if not cid:
                return None

            # 并行获取三部分数据
            props = await self._get_properties(client, cid)
            full_record = await self._get_full_record(client, cid)
            ghs_data = await self._get_ghs_data(client, cid)

            return {
                "identifiers": self._extract_identifiers(props, full_record),
                "properties": self._extract_properties(props, full_record),
                "safety": self._extract_safety(ghs_data, full_record) if ghs_data else {},
                "raw_pubchem_full": full_record,  # 保留原始数据供后续验证
            }

    async def fetch_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(verify=False) as client:
            cid = await self._name_to_cid(client, name)
            if not cid:
                return None

            props = await self._get_properties(client, cid)
            full_record = await self._get_full_record(client, cid)
            ghs_data = await self._get_ghs_data(client, cid)

            return {
                "identifiers": self._extract_identifiers(props, full_record),
                "properties": self._extract_properties(props, full_record),
                "safety": self._extract_safety(ghs_data, full_record) if ghs_data else {},
                "raw_pubchem_full": full_record,
            }

    # ---- 内部方法 ----

    async def _cas_to_cid(self, client: httpx.AsyncClient, cas: str) -> Optional[int]:
        """CAS 号 → PubChem CID"""
        url = f"{self.BASE_URL}/compound/name/{cas}/cids/JSON"
        data = await self._get_json(client, url)
        if data and "IdentifierList" in data:
            cids = data["IdentifierList"].get("CID", [])
            if cids:
                return int(cids[0])
        logger.warning(f"[PubChem] CAS→CID 失败: {cas}")
        return None

    async def _name_to_cid(self, client: httpx.AsyncClient, name: str) -> Optional[int]:
        """名称 → PubChem CID"""
        url = f"{self.BASE_URL}/compound/name/{name}/cids/JSON"
        data = await self._get_json(client, url)
        if data and "IdentifierList" in data:
            cids = data["IdentifierList"].get("CID", [])
            if cids:
                return int(cids[0])
        logger.warning(f"[PubChem] 名称→CID 失败: {name}")
        return None

    async def _get_properties(self, client: httpx.AsyncClient, cid: int) -> Optional[dict]:
        """获取化合物基本属性"""
        url = f"{self.BASE_URL}/compound/cid/{cid}/property/{self.PROPERTIES}/JSON"
        data = await self._get_json(client, url)
        if data and "PropertyTable" in data:
            props = data["PropertyTable"].get("Properties", [])
            if props:
                return props[0]
        return None

    async def _get_full_record(self, client: httpx.AsyncClient, cid: int) -> Optional[dict]:
        """获取完整 JSON 记录（含实验属性、分类、名称）"""
        url = f"{self.BASE_URL}/compound/cid/{cid}/record/JSON"
        data = await self._get_json(client, url)
        if data and "Record" in data:
            return data["Record"]
        # 简化版回退
        url2 = f"{self.BASE_URL}/compound/cid/{cid}/JSON"
        return await self._get_json(client, url2)

    async def _get_ghs_data(self, client: httpx.AsyncClient, cid: int) -> Optional[dict]:
        """获取 GHS 分类数据"""
        url = f"{self.BASE_URL}/compound/cid/{cid}/classification/JSON?classification_type=simple"
        data = await self._get_json(client, url)
        return data

    # ---- 数据提取方法 ----

    def _extract_identifiers(self, props: dict, record: dict) -> dict:
        """提取物质标识信息"""
        result = {}
        if props:
            result.update({
                "molecular_formula": props.get("MolecularFormula"),
                "molecular_weight": _parse_float(props.get("MolecularWeight")),
                "canonical_smiles": props.get("CanonicalSMILES"),
                "isomeric_smiles": props.get("IsomericSMILES"),
                "inchi": props.get("InChI"),
                "inchikey": props.get("InChIKey"),
                "iupac_name_en": props.get("IUPACName"),
                "name_en": props.get("Title"),
                "xlogp": _parse_float(props.get("XLogP")),
                "exact_mass": _parse_float(props.get("ExactMass")),
                "monoisotopic_mass": _parse_float(props.get("MonoisotopicMass")),
                "charge": props.get("Charge"),
                "complexity": props.get("Complexity"),
                "tpsa": _parse_float(props.get("TPSA")),
            })

        # 从完整记录提取更多名称和分类
        if record:
            # 提取同义词列表
            syns = []
            record_data = record if isinstance(record, dict) else {}
            sections = record_data.get("Section", [])
            for sec in sections:
                if sec.get("TOCHeading") == "Names and Identifiers":
                    for subsec in sec.get("Section", []):
                        if subsec.get("TOCHeading") == "Synonyms":
                            for item in subsec.get("Information", []):
                                name_val = item.get("Value", {})
                                if isinstance(name_val, dict):
                                    syns.append(name_val.get("StringWithMarkup", [{}])[0].get("String", ""))
                                elif isinstance(name_val, str):
                                    syns.append(name_val)
            result["synonyms"] = syns[:20]  # 最多保留 20 个

        return result

    def _extract_properties(self, props: dict, record: dict) -> list[dict]:
        """提取理化属性列表"""
        results = []

        # 从 props 提取计算属性
        if props:
            prop_map = {
                "MolecularWeight": ("molecular_weight", "g/mol"),
                "XLogP": ("logp", ""),
                "HBondDonorCount": ("h_bond_donor_count", ""),
                "HBondAcceptorCount": ("h_bond_acceptor_count", ""),
                "RotatableBondCount": ("rotatable_bond_count", ""),
                "TPSA": ("tpsa", "Å²"),
                "HeavyAtomCount": ("heavy_atom_count", ""),
            }
            for src_key, (prop_type, unit) in prop_map.items():
                val = props.get(src_key)
                if val is not None:
                    results.append({
                        "property_type": prop_type,
                        "value": _parse_float(val) if isinstance(val, (int, float, str)) else val,
                        "unit": unit,
                        "source": "pubchem_computed",
                    })

        # 从完整记录提取实验属性
        if record:
            results.extend(self._extract_experimental_properties(record))

        return results

    def _extract_experimental_properties(self, record: dict) -> list[dict]:
        """从完整记录中提取实验测定的理化属性"""
        results = []
        prop_headings = {
            "Boiling Point": "boiling_point",
            "Melting Point": "melting_point",
            "Density": "density",
            "Solubility": "solubility",
            "Vapor Pressure": "vapor_pressure",
            "Refractive Index": "refractive_index",
            "Flash Point": "flash_point",
            "Autoignition Temperature": "autoignition_temperature",
            "Decomposition": "decomposition_temperature",
            "Viscosity": "viscosity",
        }

        sections = record.get("Section", []) if isinstance(record, dict) else []
        for sec in sections:
            if sec.get("TOCHeading") == "Chemical and Physical Properties":
                for subsec in sec.get("Section", []):
                    heading = subsec.get("TOCHeading", "")
                    ptype = prop_headings.get(heading)
                    if ptype:
                        for info in subsec.get("Information", []):
                            val_dict = info.get("Value", {})
                            if isinstance(val_dict, dict):
                                num = val_dict.get("Number", [None])[0]
                                unit = info.get("Unit", "")
                                results.append({
                                    "property_type": ptype,
                                    "value": _parse_float(num) if num else None,
                                    "value_text": val_dict.get("StringWithMarkup", [{}])[0].get("String", "") if not num else None,
                                    "unit": unit,
                                    "source": "pubchem_experimental",
                                })

        return results

    def _extract_safety(self, ghs_data: dict, record: dict = None) -> dict:
        """提取安全性数据"""
        result = {
            "ghs_classifications": [],
            "h_codes": [],
            "p_codes": [],
            "signal_word": "",
        }

        # GHS 分类
        if ghs_data:
            # 尝试多种可能的 JSON 结构
            classifications = (
                ghs_data.get("Classification", []) or
                ghs_data.get("GHSClassification", []) or
                []
            )
            if not classifications and isinstance(ghs_data, dict):
                # 从 Record 中提取
                record_data = ghs_data.get("Record", {})
                if record_data:
                    sections = record_data.get("Section", [])
                    for sec in sections:
                        if sec.get("TOCHeading") == "Safety and Hazards":
                            for subsec in sec.get("Section", []):
                                if "GHS" in subsec.get("TOCHeading", ""):
                                    for info in subsec.get("Information", []):
                                        val = info.get("Value", {})
                                        if isinstance(val, dict):
                                            str_val = val.get("StringWithMarkup", [{}])[0].get("String", "")
                                            if str_val:
                                                classifications.append(str_val)

            for c in (classifications or []):
                if isinstance(c, dict):
                    result["ghs_classifications"].append({
                        "code": c.get("GHSHazardStatementCode", c.get("Code", "")),
                        "label": c.get("GHSHazardStatementText", c.get("Name", str(c))),
                        "pictogram": c.get("GHSPictogram", c.get("Pictogram", "")),
                        "signal_word": c.get("GHSSignalWord", c.get("SignalWord", "")),
                    })
                    if c.get("GHSSignalWord") and not result["signal_word"]:
                        result["signal_word"] = c["GHSSignalWord"]

        # 从完整记录提取更多安全信息
        if record and isinstance(record, dict):
            sections = record.get("Section", [])
            for sec in sections:
                if sec.get("TOCHeading") == "Safety and Hazards":
                    for subsec in sec.get("Section", []):
                        heading = subsec.get("TOCHeading", "")
                        infos = subsec.get("Information", [])

                        if "Hazard" in heading:
                            for info in infos:
                                val = info.get("Value", {})
                                if isinstance(val, dict):
                                    str_val = (
                                        val.get("StringWithMarkup", [{}])[0].get("String", "") if hasattr(val, 'get') else str(val)
                                    )
                                    if str_val and str_val not in result["h_codes"]:
                                        result["h_codes"].append(str_val)

                        if heading == "NFPA Hazard Classification":
                            nfpa = {}
                            for info in infos:
                                name = info.get("Name", "")
                                val = info.get("Value", {})
                                if isinstance(val, dict):
                                    num = val.get("Number", [None])[0]
                                    if name == "Health" and num is not None:
                                        nfpa["health"] = int(num)
                                    elif name == "Flammability" and num is not None:
                                        nfpa["fire"] = int(num)
                                    elif name == "Instability" and num is not None:
                                        nfpa["reactivity"] = int(num)
                            if nfpa:
                                result["nfpa"] = nfpa

        return result


def _parse_float(val: any) -> float | None:
    """安全转换为 float"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
