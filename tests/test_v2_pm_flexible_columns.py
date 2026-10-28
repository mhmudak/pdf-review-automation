import pytest
from v2_pm_cell_plan import PM_HEADER_SEQUENCE
from v2_pm_column_mapping import PMColumnMapping


def test_reordered_selected_text_and_custom_w():
    headers=list(PM_HEADER_SEQUENCE)
    headers.insert(4,headers.pop(9))
    headers.append('')
    mapping=PMColumnMapping.from_rows([headers, ['']*23], 23)
    assert mapping.physical_cell('E2')=='F2'
    assert mapping.physical_cell('F2')=='G2'
    assert mapping.physical_cell('V2')=='V2'
    assert mapping.physical_cell('O2')=='O2'
    assert mapping.physical_cell('J2')=='E2'
    assert mapping.canonical_rows([headers,list(range(23))])[1][9]=='4'
    assert mapping.physical_row(['x']*22)[22]==''


def test_arbitrary_managed_reordering():
    headers=list(reversed(PM_HEADER_SEQUENCE))+['PM Notes']
    mapping=PMColumnMapping.from_rows([headers],23)
    assert mapping.physical_cell('O7')=='H7'
    assert mapping.physical_cell('E7')=='R7'
    row=mapping.physical_row([f'v{i}' for i in range(22)])
    assert mapping.canonical_rows([headers,row])[1]==[f'v{i}' for i in range(22)]
    assert row[22]==''


def test_unnamed_custom_data_rejected():
    with pytest.raises(RuntimeError,match='PM_UNNAMED_COLUMN_WITH_DATA'):
        PMColumnMapping.from_rows([PM_HEADER_SEQUENCE+[''],['']*22+['human']],23)


def test_duplicate_header_rejected():
    with pytest.raises(RuntimeError,match='PM_DUPLICATE_HEADER'):
        PMColumnMapping.from_rows([PM_HEADER_SEQUENCE+['Comment']],23)


def test_missing_managed_header_rejected():
    headers=list(PM_HEADER_SEQUENCE)
    headers[3]='Different name'
    with pytest.raises(RuntimeError,match='PM_MISSING_MANAGED_HEADER'):
        PMColumnMapping.from_rows([headers],22)


def test_header_change_detected():
    mapping=PMColumnMapping.from_rows([PM_HEADER_SEQUENCE],22)
    changed=list(PM_HEADER_SEQUENCE)
    changed[5]='different'
    with pytest.raises(RuntimeError,match='PM_HEADERS_CHANGED_DURING_EXPORT'):
        mapping.canonical_rows([changed])


def test_guarded_cell_writer_uses_moved_root_and_comment_columns():
    from v2_pm_safe_writer import GuardedPMWriter, CellChange
    from unittest.mock import MagicMock
    headers = list(PM_HEADER_SEQUENCE)
    headers.insert(4, headers.pop(9))
    headers.append('')
    mapping = PMColumnMapping.from_rows([headers],23)
    service = MagicMock()
    # Header probe then rooted cell probes: write=False -> no mutation
    service.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = [
        {'values':[headers]},
        {'values':[['root-1']]},
        {'values':[['before']]},
        {'values':[['before']]},
    ]
    writer = GuardedPMWriter(service, 'staging', 'Trial PDF - All Data',
        authorized_spreadsheet_id='staging', authorized_tab='Trial PDF - All Data',
        column_mapping=mapping)
    result=writer.apply([CellChange(root_id='root-1',cell='F2',expected_value='before',new_value='after')])
    assert result['pending']==['F2']
    requested=[call.kwargs['range'] for call in service.spreadsheets.return_value.values.return_value.get.call_args_list]
    assert "'Trial PDF - All Data'!O2" in requested
    assert "'Trial PDF - All Data'!F2" in requested
    assert not service.spreadsheets.return_value.values.return_value.batchUpdate.called


def test_guarded_writer_rejects_nonowned_field_after_reorder():
    from v2_pm_safe_writer import GuardedPMWriter, CellChange
    from unittest.mock import MagicMock
    headers=list(PM_HEADER_SEQUENCE)
    headers.insert(4,headers.pop(9))
    mapping=PMColumnMapping.from_rows([headers],22)
    service=MagicMock()
    service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value={'values':[headers]}
    writer=GuardedPMWriter(service,'staging','Trial PDF - All Data',authorized_spreadsheet_id='staging',authorized_tab='Trial PDF - All Data',column_mapping=mapping)
    with pytest.raises(ValueError,match='Unapproved output column'):
        writer.apply([CellChange(root_id='r',cell='E2',expected_value='',new_value='do not overwrite')])
