"""予測・シミュレーションで共有する全頭スコアと購入馬・購入額の決定。"""
import numpy as np
import pandas as pd


def make_candidates(predictions, top_n=5, normalization="auto", temperature=1.0):
    df = predictions.copy()
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperatureは0より大きい有限の数値にしてください。")
    regression = "predicted_rank" in df
    if regression and normalization == "none":
        raise ValueError("着順回帰モデルではsoftmaxが必要です。--normalization autoまたはsoftmaxを指定してください。")
    if normalization == "auto":
        normalization = "softmax" if regression else "none"
    df["pred_prob"] = -df["predicted_rank"] if regression else df["pred_prob_first"]
    if normalization == "softmax":
        def softmax(values):
            # 最大値を引いてから温度で割り、絶対値の大きいrankでも安定させる。
            scaled = (values - values.max()) / temperature
            exp = np.exp(scaled)
            return exp / exp.sum()
        # top_nやオッズ条件で絞る前に、レース全頭で正規化する。
        df["pred_prob"] = df.groupby("race_id", sort=False)["pred_prob"].transform(softmax)
    df["expected_value"] = df["ods"] * df["pred_prob"]
    df["kelly_fraction"] = ((df["expected_value"] - 1) / (df["ods"] - 1)).where(df["ods"] > 1, 0)
    # 予測確率で候補を絞ってから、オッズと期待値の購入条件を適用する。
    order = (df.groupby("race_id", sort=False)["predicted_rank"].rank(method="first", ascending=True)
             if regression else df.groupby("race_id", sort=False)["pred_prob"].rank(method="first", ascending=False))
    return df[order <= top_n].copy()



def eligible_candidates(candidates, ev_threshold=1.0, max_odds=30.0):
    """top-n候補のうち、しきい値とオッズ条件を満たす全頭を返す。"""
    return candidates[
        np.isfinite(candidates['ods']) & (candidates['ods'] > 1)
        & (candidates['ods'] <= max_odds) & (candidates['expected_value'] > ev_threshold)
    ].copy()


def select_purchases(candidates, ev_threshold=1.0, max_odds=30.0,
                     staking='expected-value', base_bet=100):
    eligible = eligible_candidates(candidates, ev_threshold, max_odds)
    selected = eligible.loc[eligible.groupby('race_id', sort=False)['expected_value'].idxmax()].copy()
    if staking == 'fixed':
        amounts = np.full(len(selected), base_bet)
    elif staking == 'kelly':
        amounts = base_bet * selected['kelly_fraction'].clip(lower=0).to_numpy()
    elif staking == 'expected-value':
        amounts = base_bet * np.trunc(selected['expected_value'].to_numpy())
    else:
        raise ValueError(f'不明な購入額方式: {staking}')
    selected['bet_amount'] = np.trunc(amounts).astype(int)
    return selected[selected['bet_amount'] > 0].copy()
