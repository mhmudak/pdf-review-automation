import copy
import pytest
from v2_pm_dynamic_source_snapshot import create_table, read_table, validate_headers


def row(root='r', depth=3):
    record = {'Root Entry ID': root, 'Comment': 'hello'}
    for n in range(1, depth + 1):
        record[f'Reply {n}'] = f'author — body {n}\\n2026-10-22'
    record['Reply Entry IDs'] = ' | '.join(f'id{n}' for n in range(1, depth + 1))
    return record


def test_legacy_schema_and_digest_roundtrip():
    t = create_table([row(depth=3)])
    assert len(t[0]) == 8
    assert t[0][5] == 'Reply Entry IDs'
    assert read_table(t)[0]['Reply 3'] == row()['Reply 3']


def test_dynamic_reply_four_and_five_roundtrip():
    for n in (4, 5):
        t = create_table([row(depth=n), row('z', 1)])
        assert len(t[0]) == n + 5
        assert t[0][n + 2] == 'Reply Entry IDs'
        assert read_table(t)[0][f'Reply {n}'] == row(depth=n)[f'Reply {n}']
        assert read_table(t)[1][f'Reply {n}'] == ''


def test_data_tampering_detected_in_reply_four():
    t = create_table([row(depth=4)])
    t[1][5] = 'modified'
    with pytest.raises(RuntimeError, match='ROW_TAMPERED'):
        read_table(t)


def test_snapshot_signature_tampering_detected():
    t = create_table([row(depth=5)])
    t[1][-1] = 'untrusted'
    with pytest.raises(RuntimeError, match='DIGEST_MISMATCH'):
        read_table(t)


def test_noncontiguous_reply_values_rejected():
    value = row(depth=4)
    value['Reply 3'] = ''
    with pytest.raises(RuntimeError, match='REPLY_GAP'):
        create_table([value])


def test_reply_id_mismatch_rejected():
    value = row(depth=4)
    value['Reply Entry IDs'] = 'id1 | id2 | id3'
    with pytest.raises(RuntimeError, match='ID_MISMATCH'):
        create_table([value])


def test_headers_require_contiguous_numbers():
    t = create_table([row(depth=4)])
    t[0][5] = 'Reply 9'
    with pytest.raises(RuntimeError, match='SCHEMA_CONFLICT'):
        validate_headers(t[0])


def test_duplicate_roots_rejected():
    with pytest.raises(RuntimeError, match='ID_CONFLICT'):
        create_table([row(), row()])


def test_legacy_snapshot_digest_matches_previous_contract():
    import hashlib, json
    def digest(x):
        return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode('utf-8')).hexdigest()
    rows = [row('b', 1), row('a', 3)]
    old_fields = []
    for r in sorted(rows, key=lambda r: r['Root Entry ID']):
        old_fields.append([r['Root Entry ID'], r['Comment'],
            r.get('Reply 1', ''), r.get('Reply 2', ''), r.get('Reply 3', ''),
            r['Reply Entry IDs']])
    old_signature = digest(old_fields)
    table = create_table(rows)
    assert all(r[-1] == old_signature for r in table[1:])
    assert all(r[-2] == digest(r[:-2]) for r in table[1:])


def test_reply_four_timestamp_change_changes_digest():
    base = row(depth=4)
    amended = copy.deepcopy(base)
    amended['Reply 4'] += 'changed'
    assert create_table([base])[1][-1] != create_table([amended])[1][-1]


def test_duplicate_reply_ids_rejected():
    value = row(depth=4)
    value['Reply Entry IDs'] = 'id1 | id2 | id2 | id4'
    with pytest.raises(RuntimeError, match='ID_MISMATCH'):
        create_table([value])
