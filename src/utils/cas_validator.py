"""
CAS 号校验工具

CAS 号格式: XXXXXX-XX-X
最后一位是校验位，计算方式:
  从右向左，每位乘以递增的权重(1,2,3,...)，求和后 mod 10 应等于校验位。
"""
import re

CAS_PATTERN = re.compile(r"^(\d{2,7})-(\d{2})-(\d{1})$")


def validate_cas(cas_number: str) -> bool:
    """验证 CAS 号的校验位是否正确"""
    match = CAS_PATTERN.match(cas_number.strip())
    if not match:
        return False

    # 去掉横线，取数字部分
    digits = cas_number.replace("-", "")
    check_digit = int(digits[-1])
    payload = digits[:-1]  # 除校验位外的部分

    # 从右向左计算校验和
    total = 0
    for i, ch in enumerate(reversed(payload), start=1):
        total += i * int(ch)

    return (total % 10) == check_digit


def normalize_cas(cas_number: str) -> str:
    """规范化 CAS 号为标准格式 XXXXXX-XX-X"""
    cleaned = re.sub(r"[^\d-]", "", cas_number.strip())
    match = CAS_PATTERN.match(cleaned)
    if match:
        return cleaned
    # 尝试去除横线后重新格式化
    digits_only = re.sub(r"\D", "", cleaned)
    if len(digits_only) >= 5:
        return f"{digits_only[:-3]}-{digits_only[-3:-1]}-{digits_only[-1]}"
    return cleaned
