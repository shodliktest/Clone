"""Regression tests for Premium admin input parsing."""

def parse_input(raw: str, mode: str):
    raw = (raw or '').strip()
    if raw.lower() == '/cancel':
        return ('cancel',)
    parts = raw.replace(',', ' ').split()
    if mode == 'revoke':
        if len(parts) != 1 or not parts[0].isdigit():
            raise ValueError('invalid user id')
        return int(parts[0]), None
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError('expected USER_ID KUN')
    uid, days = int(parts[0]), int(parts[1])
    if not 5 <= len(parts[0]) <= 15:
        raise ValueError('invalid telegram id')
    if not 1 <= days <= 3650:
        raise ValueError('days out of range')
    return uid, days

valid = [
    ('7078456772 30', 'add', (7078456772, 30)),
    ('123456789 1', 'add', (123456789, 1)),
    ('123456789 3650', 'extend', (123456789, 3650)),
    ('7078456772,30', 'add', (7078456772, 30)),
    ('7078456772', 'revoke', (7078456772, None)),
]
for raw, mode, expected in valid:
    assert parse_input(raw, mode) == expected, (raw, mode)

invalid = [
    ('7078456772', 'add'),
    ('7078456772 0', 'add'),
    ('7078456772 3651', 'add'),
    ('123 30', 'add'),
    ('7078456772 30 abc', 'add'),
    ('abc', 'revoke'),
]
for raw, mode in invalid:
    try:
        parse_input(raw, mode)
    except ValueError:
        pass
    else:
        raise AssertionError(f'accepted invalid input: {raw!r}')
print('PREMIUM_ADMIN_INPUT_TESTS_PASSED')
