"""CLI validators without training/simulation dependencies."""
import argparse
import math


def positive_float(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("0より大きい有限の数値を指定してください。")
    return value


def positive_int(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("1以上の整数を指定してください。")
    return value
