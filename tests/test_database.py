"""Tests for database.py — unit and integration."""

import csv
import io
import pytest

from database import (
    DatabaseManager,
    generate_unique_code,
    load_data_from_file,
    _fix_shifted_row,
)


# ---------------------------------------------------------------------------
# generate_unique_code
# ---------------------------------------------------------------------------

class TestGenerateUniqueCode:
    def test_returns_md5_hex(self):
        code = generate_unique_code("SALA 101")
        assert len(code) == 32
        assert all(c in "0123456789abcdef" for c in code)

    def test_same_input_same_code(self):
        assert generate_unique_code("SALA 101") == generate_unique_code("SALA 101")

    def test_different_inputs_different_codes(self):
        assert generate_unique_code("SALA 101") != generate_unique_code("SALA 102")

    def test_none_returns_none(self):
        assert generate_unique_code(None) is None

    def test_empty_string_returns_none(self):
        assert generate_unique_code("") is None

    def test_raises_on_collision(self):
        code = generate_unique_code("SALA 101")
        with pytest.raises(ValueError, match="Colisão"):
            generate_unique_code("SALA 101", existing_codes={code})

    def test_no_raise_when_code_not_in_existing(self):
        code = generate_unique_code("SALA 101", existing_codes={"other_code"})
        assert code is not None


# ---------------------------------------------------------------------------
# _fix_shifted_row
# ---------------------------------------------------------------------------

class TestFixShiftedRow:
    def _make_row(self, valor_aquisicao):
        return {
            '#': '1',
            'NUMERO': '12345',
            'STATUS': 'Ativo',
            'ED': 'ED01',
            'DESCRICAO': 'MESA',
            'RÓTULOS': 'rotulo',
            'CARGA ATUAL': 'SETOR A',
            'SETOR DO RESPONSÁVEL': 'CAMPUS X',
            'CAMPUS DA CARGA': 'BLV',
            'VALOR AQUISIÇÃO': valor_aquisicao,
            'VALOR DEPRECIADO': '100.00',
            'NUMERO NOTA FISCAL': 'NF001',
            'NÚMERO DE SÉRIE': 'SN001',
            'DATA DA ENTRADA': '2020-01-01',
            'DATA DA CARGA': '2020-01-02',
            'FORNECEDOR': 'FORNECEDOR X',
            'SALA': 'SALA 101',
            'ESTADO DE CONSERVAÇÃO': 'Bom',
            '': '',
        }

    def test_no_shift_returns_same_row(self):
        row = self._make_row('500.00')
        result = _fix_shifted_row(row)
        assert result is row

    def test_shift_detected_and_corrected(self):
        row = self._make_row('BLV')  # non-numeric → shifted
        result = _fix_shifted_row(row)
        assert result is not row
        # After correction, VALOR AQUISIÇÃO should be '100.00' (was VALOR DEPRECIADO)
        assert result['VALOR AQUISIÇÃO'] == '100.00'

    def test_shift_concatenates_descricao(self):
        row = self._make_row('BLV')
        row['DESCRICAO'] = 'MARCA'
        row['RÓTULOS'] = 'USE MOVEIS'
        result = _fix_shifted_row(row)
        assert result['DESCRICAO'] == 'MARCA, USE MOVEIS'

    def test_empty_valor_aquisicao_returns_same_row(self):
        row = self._make_row('')
        result = _fix_shifted_row(row)
        assert result is row


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------

class TestDatabaseManager:
    def test_init_creates_tables(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in db.cursor.fetchall()}
        assert {"salas", "patrimonios", "patrimonios_nao_cadastrados"}.issubset(tables)
        db.close()

    def test_get_all_salas_empty(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        assert db.get_all_salas() == []
        db.close()

    def test_get_patrimonios_by_sala_empty(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        assert db.get_patrimonios_by_sala(1) == []
        db.close()

    def test_close_idempotent(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.close()
        db.close()  # should not raise

    def test_mark_patrimonio_encontrado(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("INSERT INTO salas (id, sala, codigo) VALUES (1, 'SALA A', 'abc')")
        db.cursor.execute(
            "INSERT INTO patrimonios (numero, sala_id, encontrado) VALUES ('P001', 1, 0)"
        )
        db.conn.commit()

        result = db.mark_patrimonio_encontrado('P001', 1)
        assert result is True

        db.cursor.execute("SELECT encontrado FROM patrimonios WHERE numero = 'P001'")
        assert db.cursor.fetchone()[0] == 1
        db.close()

    def test_mark_patrimonio_encontrado_nonexistent(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        result = db.mark_patrimonio_encontrado('NONEXISTENT', 1)
        assert result is False
        db.close()

    def test_record_unfound_patrimonio(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("INSERT INTO salas (id, sala, codigo) VALUES (1, 'SALA A', 'abc')")
        db.conn.commit()

        db.record_unfound_patrimonio('P999', 1)
        rows = db.get_unfound_patrimonios()
        assert len(rows) == 1
        assert rows[0][2] == 'P999'
        db.close()

    def test_get_patrimonios_by_sala_returns_13_fields(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("INSERT INTO salas (id, sala, codigo) VALUES (1, 'SALA A', 'abc')")
        db.cursor.execute(
            "INSERT INTO patrimonios (numero, sala_id, sala_id_original, encontrado) VALUES ('P001', 1, 1, 0)"
        )
        db.conn.commit()

        rows = db.get_patrimonios_by_sala(1)
        assert len(rows) == 1
        assert len(rows[0]) == 13
        db.close()


# ---------------------------------------------------------------------------
# load_data_from_file
# ---------------------------------------------------------------------------

VALID_HEADERS = (
    '#,NUMERO,STATUS,ED,DESCRICAO,RÓTULOS,CARGA ATUAL,SETOR DO RESPONSÁVEL,'
    'CAMPUS DA CARGA,VALOR AQUISIÇÃO,VALOR DEPRECIADO,NUMERO NOTA FISCAL,'
    'NÚMERO DE SÉRIE,DATA DA ENTRADA,DATA DA CARGA,FORNECEDOR,SALA,ESTADO DE CONSERVAÇÃO,\n'
)

VALID_ROW = (
    '1,P001,Ativo,ED01,Mesa,,SETOR A,RESP A,BLV,500.00,400.00,NF001,'
    'SN001,2020-01-01,2020-01-02,FORN A,SALA 101,Bom,\n'
)


def _make_csv(rows: list[str]) -> str:
    return VALID_HEADERS + "".join(rows)


class TestLoadDataFromFile:
    def test_loads_valid_csv(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(_make_csv([VALID_ROW]), encoding="utf-8")

        db = DatabaseManager(db_path=tmp_path / "test.db")
        load_data_from_file(db.cursor, db.conn, str(csv_path))

        salas = db.get_all_salas()
        assert len(salas) == 1
        assert salas[0][1] == "SALA 101"

        rows = db.get_patrimonios_by_sala(salas[0][0])
        assert len(rows) == 1
        assert rows[0][0] == "P001"
        db.close()

    def test_invalid_csv_does_not_delete_existing_data(self, tmp_path):
        db = DatabaseManager(db_path=tmp_path / "test.db")
        db.cursor.execute("INSERT INTO salas (id, sala, codigo) VALUES (1, 'EXISTENTE', 'abc')")
        db.conn.commit()

        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("COL1,COL2\nval1,val2\n", encoding="utf-8")
        load_data_from_file(db.cursor, db.conn, str(bad_csv))

        salas = db.get_all_salas()
        assert len(salas) == 1
        assert salas[0][1] == "EXISTENTE"
        db.close()

    def test_multiple_salas(self, tmp_path):
        row2 = (
            '2,P002,Ativo,ED01,Cadeira,,SETOR B,RESP B,BLV,200.00,150.00,NF002,'
            'SN002,2020-02-01,2020-02-02,FORN B,SALA 202,Bom,\n'
        )
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(_make_csv([VALID_ROW, row2]), encoding="utf-8")

        db = DatabaseManager(db_path=tmp_path / "test.db")
        load_data_from_file(db.cursor, db.conn, str(csv_path))

        salas = db.get_all_salas()
        assert len(salas) == 2
        db.close()
