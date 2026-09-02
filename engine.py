# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 数据引擎
=============================================
读取 CSV 为结构化列表，提供窗口切片（保证公式只访问历史、不偷看未来）。
列：issue,hundreds,tens,ones（无日期列）。
"""
import csv

CSV_PATH = 'data/fc3d-history.csv'


def load_data(csv_path=CSV_PATH):
    """读取 CSV，返回 (issues, hundreds, tens, ones)，校验严格升序，乱序则排序修复"""
    issues, hundreds, tens, ones = [], [], [], []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                issues.append(row['issue'])
                hundreds.append(int(row['hundreds']))
                tens.append(int(row['tens']))
                ones.append(int(row['ones']))
            except (KeyError, ValueError):
                continue
    if not issues:
        raise ValueError(
            f"CSV 无有效数据：{csv_path} 为空或表头/字段损坏（需列 issue,hundreds,tens,ones）。"
            f"请检查数据文件。")
    if any(issues[i] >= issues[i + 1] for i in range(len(issues) - 1)):
        order = sorted(range(len(issues)), key=lambda i: int(issues[i]))
        issues = [issues[i] for i in order]
        hundreds = [hundreds[i] for i in order]
        tens = [tens[i] for i in order]
        ones = [ones[i] for i in order]
    return issues, hundreds, tens, ones


def get_next_issue(latest_issue):
    year = int(latest_issue[:4])
    seq = int(latest_issue[4:]) + 1
    if seq > 359:
        year += 1
        seq = 1
    return f"{year}{seq:03d}"


if __name__ == '__main__':
    issues, h, t, o = load_data()
    print(f"数据 {len(issues)} 期：{issues[0]} ~ {issues[-1]}")
    print(f"最新一期 {issues[-1]} = {h[-1]}{t[-1]}{o[-1]}")
    print(f"下期期号：{get_next_issue(issues[-1])}")
