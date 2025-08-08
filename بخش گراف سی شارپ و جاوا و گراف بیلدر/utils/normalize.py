import os
import re


def normalize_test_name(raw_name: str) -> str:
    """
    نرمال‌سازی نام تست برای تطبیق بهتر با گره گراف.
    تبدیل نام تست به فرمت: <filename>.py::<class>::<function> یا <filename>.py::<function>
    - حذف مسیرهای اضافی (tests/, test/, src/)
    - یکسان‌سازی جداکننده ویندوز/یونیکس
    """
    if not raw_name or not isinstance(raw_name, str):
        return raw_name

    name = raw_name.strip().replace("\\", "/")

    # جدا کردن بخش فایل و تابع
    if "::" in name:
        path_part, func_part = name.split("::", 1)
    else:
        path_part, func_part = name, ""

    # حذف دایرکتوری‌های بی‌اهمیت
    segments = [
        seg
        for seg in path_part.split("/")
        if seg.lower() not in {"tests", "test", "src"}
    ]
    filename = segments[-1] if segments else "unknown.py"
    if not filename.endswith(".py"):
        filename += ".py"

    normalized = filename
    if func_part:
        normalized += f"::{func_part.strip()}"

    return normalized
