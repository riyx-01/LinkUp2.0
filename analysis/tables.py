"""Dependency-free Markdown and LaTeX table rendering."""

from __future__ import annotations

import math

import pandas as pd


def _fmt(value, digits: int) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if math.isnan(value):
            return "-"
        return f"{value:.{digits}f}"
    return str(value)


def md_table(df: pd.DataFrame, digits: int = 2, index: bool = False) -> str:
    if index:
        df = df.reset_index()
    if df.empty:
        return "_(no data)_"
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    rows = ["| " + " | ".join(_fmt(v, digits).replace("|", r"\|") for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([header, sep, *rows])


def _latex_escape(text: str) -> str:
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#"),
                 ("$", r"\$"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}")):
        text = text.replace(a, b)
    return text


def latex_table(df: pd.DataFrame, caption: str, label: str, digits: int = 2) -> str:
    cols = "l" * len(df.columns)
    lines = [r"\begin{table}[htbp]", r"\centering", rf"\caption{{{_latex_escape(caption)}}}",
             rf"\label{{{label}}}", rf"\begin{{tabular}}{{{cols}}}", r"\hline",
             " & ".join(_latex_escape(str(c)) for c in df.columns) + r" \\", r"\hline"]
    for row in df.itertuples(index=False):
        lines.append(" & ".join(_latex_escape(_fmt(v, digits)) for v in row) + r" \\")
    lines += [r"\hline", r"\end{tabular}", r"\end{table}"]
    return "\n".join(lines)
