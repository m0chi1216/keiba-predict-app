"""予測とシミュレーションで共用する購入条件JSONの読み込み。"""
import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETTING_KEYS = {
    'model', 'test_data', 'normalization', 'temperature', 'top_n', 'score_threshold',
    'max_odds', 'staking', 'base_bet', 'exclude_grade', 'bet_type', 'task',
}


def apply_config_defaults(parser, argv=None):
    """JSONを既定値として適用する。明示CLI引数を優先する。"""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--config', type=Path)
    known, _ = pre.parse_known_args(argv)
    if known.config is None:
        return None
    with known.config.open(encoding='utf-8') as file:
        config = json.load(file)
    if config.get('schema_version') != 1 or not isinstance(config.get('settings'), dict):
        parser.error('configはschema_version=1とsettingsオブジェクトを持つJSONにしてください。')
    settings = config['settings'].copy()
    unknown = set(settings) - SETTING_KEYS
    if unknown:
        parser.error(f'configに不明な設定があります: {sorted(unknown)}')
    required = SETTING_KEYS - {'test_data'}
    if required - set(settings):
        parser.error(f'configに必要な設定がありません: {sorted(required - set(settings))}')
    for key in ('model', 'test_data'):
        if key in settings:
            path = Path(settings[key])
            settings[key] = path if path.is_absolute() else PROJECT_ROOT / path
    settings['ev_threshold'] = settings.pop('score_threshold')
    settings['expected_task'] = settings.pop('task')
    # argparseはJSON数値のdefaultにはtype/choices検証を行わないため、明示検証する。
    for key in ('normalization', 'staking', 'bet_type'):
        allowed = {'normalization': {'auto', 'none', 'softmax'},
                   'staking': {'expected-value', 'fixed', 'kelly'},
                   'bet_type': {'win', 'place', 'both'}}[key]
        if settings[key] not in allowed:
            parser.error(f'configの{key}が不正です。')
    if settings['expected_task'] not in {'classification', 'regression'}:
        parser.error('configのtaskが不正です。')
    import math
    for key in ('temperature', 'ev_threshold', 'max_odds', 'top_n', 'base_bet'):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            parser.error(f'configの{key}は正の有限数にしてください。')
    for key in ('top_n', 'base_bet'):
        if not isinstance(settings[key], int):
            parser.error(f'configの{key}は整数にしてください。')
    grade = settings['exclude_grade']
    if grade is not None and (isinstance(grade, bool) or not isinstance(grade, (int, float)) or not math.isfinite(grade)):
        parser.error('configのexclude_gradeは数値またはnullにしてください。')
    parser.set_defaults(**settings)
    return config
