import warnings
# Suprimir todos os DeprecationWarning antes de qualquer importação
warnings.filterwarnings("ignore", category=DeprecationWarning)

import logging

from PyQt5.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QWidget, QHBoxLayout,
    QSpacerItem, QSizePolicy, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLineEdit, QComboBox, QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QBrush, QColor
from report_generator import ReportGenerator, ReportWorker

logger = logging.getLogger(__name__)


class LoadWorker(QThread):
    """Carrega um CSV exportado do SUAP em thread separada, evitando congelamento da UI."""

    finished = pyqtSignal(int, int)  # (n_patrimonios, n_salas)
    error = pyqtSignal(str)

    def __init__(self, db_manager, file_path):
        super().__init__()
        self.db_manager = db_manager
        self.file_path = file_path

    def run(self):
        """Executa parsing e gravação no banco em segundo plano."""
        try:
            from database import _parse_csv
            sala_data, patrimonios_data = _parse_csv(self.file_path)

            cursor = self.db_manager.cursor
            conn = self.db_manager.conn
            cursor.execute("DELETE FROM patrimonios")
            cursor.execute("DELETE FROM patrimonios_nao_cadastrados")
            cursor.execute("DELETE FROM salas")
            for sala in sala_data:
                cursor.execute(
                    "INSERT INTO salas (id, sala, codigo) VALUES (?, ?, ?)",
                    (sala['id'], sala['sala'], sala['codigo'])
                )
            cursor.executemany('''
                INSERT INTO patrimonios (
                    numero, status, ed, descricao, rotulos, carga_atual,
                    setor_responsavel, campus_carga, valor_aquisicao,
                    valor_depreciado, numero_nota_fiscal, numero_de_serie,
                    data_da_entrada, data_da_carga, fornecedor, sala_id,
                    estado_de_conservacao, encontrado, sala_id_original
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', patrimonios_data)
            conn.commit()
            logger.info(
                "Arquivo carregado: %d patrimônios, %d salas — %s",
                len(patrimonios_data), len(sala_data), self.file_path,
            )
            self.finished.emit(len(patrimonios_data), len(sala_data))
        except Exception as e:
            logger.error("Falha ao carregar arquivo '%s': %s", self.file_path, e)
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self, db_manager):
        super().__init__()
        self.setWindowTitle("SUAP-CP - Conferência de Patrimônio")
        self.db_manager = db_manager
        self.filter_mode = "all"  # Modo de filtro inicial: todos
        self.report_generator = ReportGenerator(db_manager)
        self._report_worker: ReportWorker | None = None
        self._load_worker: LoadWorker | None = None

        # Layout principal
        layout = QVBoxLayout()

        # Espaçador superior reduzido
        layout.addItem(QSpacerItem(20, 10, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # Título
        label = QLabel("Bem-vindo ao SUAP-CP!", self)
        label.setFont(QFont("Arial", 16))
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        # Layout horizontal para botões de ação
        button_layout = QHBoxLayout()

        # Botão para abrir janela de escaneamento
        scan_button = QPushButton("Escanear Patrimônios")
        scan_button.setFont(QFont("Arial", 12))
        scan_button.clicked.connect(self.open_scan_window)
        button_layout.addWidget(scan_button)

        # Botão para gerar relatório
        self.report_button = QPushButton("Gerar Relatório")
        self.report_button.setFont(QFont("Arial", 12))
        self.report_button.clicked.connect(self.start_report_generation)
        button_layout.addWidget(self.report_button)

        layout.addLayout(button_layout)

        # Campo de busca global por número de patrimônio
        self.busca_input = QLineEdit()
        self.busca_input.setFont(QFont("Arial", 12))
        self.busca_input.setPlaceholderText("Buscar patrimônio por número (busca global)...")
        self.busca_input.textChanged.connect(self._on_busca_changed)
        layout.addWidget(self.busca_input)

        # Campo de filtro para salas
        self.filter_input = QLineEdit()
        self.filter_input.setFont(QFont("Arial", 12))
        self.filter_input.setPlaceholderText("Filtrar salas...")
        self.filter_input.textChanged.connect(self.filter_salas)
        layout.addWidget(self.filter_input)

        # Tabela para selecionar salas (com progresso por sala)
        self.sala_table = QTableWidget(self)
        self.sala_table.setColumnCount(2)
        self.sala_table.setHorizontalHeaderLabels(["Nome da Sala", "Progresso"])
        self.sala_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.sala_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.sala_table.setFont(QFont("Arial", 10))
        self.sala_table.setSelectionMode(QTableWidget.SingleSelection)
        self.sala_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sala_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.populate_sala_table("")  # Inicializar sem filtro
        self.sala_table.clicked.connect(self._on_sala_clicked)
        layout.addWidget(self.sala_table, stretch=1)

        # ComboBox para filtro de encontrado
        self.filter_combo = QComboBox()
        self.filter_combo.setFont(QFont("Arial", 12))
        self.filter_combo.addItems(["Todos", "Encontrados", "Não Encontrados"])
        self.filter_combo.currentIndexChanged.connect(self.update_filter_mode)
        layout.addWidget(self.filter_combo)

        # Legenda de cores acima da tabela de patrimônios
        layout.addLayout(self._build_legenda())

        # Tabela para exibir patrimônios (13 colunas — última usada na busca global)
        self.patrimonio_table = QTableWidget(self)
        self.patrimonio_table.setColumnCount(13)
        self.patrimonio_table.setHorizontalHeaderLabels([
            "Número", "Status", "ED", "Descrição", "Rótulos", "Carga Atual",
            "Setor Responsável", "Campus Carga", "Número de Série", "Estado Conservação",
            "Encontrado", "Sala Original", "Sala Atual",
        ])
        self.patrimonio_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.patrimonio_table.setFont(QFont("Arial", 10))
        self.patrimonio_table.setEditTriggers(QTableWidget.NoEditTriggers)
        # Ocultar coluna "Sala Atual" por padrão (só aparece na busca global)
        self.patrimonio_table.setColumnHidden(12, True)
        layout.addWidget(self.patrimonio_table, stretch=1)

        # Rodapé: estatísticas à esquerda e botão de carga à direita
        footer_layout = QHBoxLayout()

        stats_layout = QVBoxLayout()
        self.total_label = QLabel("Total de Patrimônios: 0")
        self.total_label.setFont(QFont("Arial", 12))
        stats_layout.addWidget(self.total_label)

        self.encontrados_label = QLabel("Patrimônios Encontrados: 0")
        self.encontrados_label.setFont(QFont("Arial", 12))
        stats_layout.addWidget(self.encontrados_label)

        footer_layout.addLayout(stats_layout)
        footer_layout.addStretch()

        # Botão para carregar arquivo CSV
        self.load_button = QPushButton("Carregar Arquivo")
        self.load_button.setFont(QFont("Arial", 12))
        self.load_button.setMinimumHeight(48)
        self.load_button.setMinimumWidth(180)
        self.load_button.clicked.connect(self.carregar_arquivo)
        footer_layout.addWidget(self.load_button)

        layout.addLayout(footer_layout)

        # Espaçador inferior reduzido
        layout.addItem(QSpacerItem(20, 10, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # Container
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    # ------------------------------------------------------------------
    # Construção de widgets auxiliares
    # ------------------------------------------------------------------

    def _build_legenda(self):
        """Constrói a linha de legenda de cores para a tabela de patrimônios."""
        legenda_layout = QHBoxLayout()
        legenda_layout.addStretch()

        itens = [
            ("#90EE90", "Encontrado nesta sala"),
            ("#FFFF00", "Encontrado em outra sala (divergente)"),
        ]
        for cor_hex, texto in itens:
            quadrado = QLabel()
            quadrado.setFixedSize(16, 16)
            quadrado.setStyleSheet(
                f"background-color: {cor_hex}; border: 1px solid #888;"
            )
            rotulo = QLabel(texto)
            rotulo.setFont(QFont("Arial", 9))
            legenda_layout.addWidget(quadrado)
            legenda_layout.addWidget(rotulo)
            legenda_layout.addSpacing(20)

        legenda_layout.addStretch()
        return legenda_layout

    # ------------------------------------------------------------------
    # Tabela de salas
    # ------------------------------------------------------------------

    def populate_sala_table(self, filter_text):
        """Popula a tabela de salas com nome e progresso de escaneamento."""
        stats = self.db_manager.get_sala_stats()  # (id, nome, total, encontrados)
        filtered = [
            (sid, nome, total, enc)
            for sid, nome, total, enc in stats
            if filter_text.lower() in nome.lower()
        ]
        self.sala_table.setRowCount(len(filtered))
        cor_concluida = QColor(144, 238, 144)
        for row_idx, (sid, nome, total, enc) in enumerate(filtered):
            item_nome = QTableWidgetItem(nome)
            item_nome.setData(Qt.UserRole, sid)

            pct = int(enc / total * 100) if total > 0 else 0
            item_prog = QTableWidgetItem(f"{int(enc)} / {total} ({pct}%)")
            item_prog.setTextAlignment(Qt.AlignCenter)

            # Colorir linha quando a sala estiver 100% concluída
            if total > 0 and enc >= total:
                item_nome.setBackground(QBrush(cor_concluida))
                item_prog.setBackground(QBrush(cor_concluida))

            self.sala_table.setItem(row_idx, 0, item_nome)
            self.sala_table.setItem(row_idx, 1, item_prog)

    def filter_salas(self):
        """Atualiza a tabela de salas com base no texto do filtro."""
        self.populate_sala_table(self.filter_input.text().strip())

    def _on_sala_clicked(self):
        """Limpa a busca global e exibe patrimônios da sala selecionada."""
        if self.busca_input.text():
            # Silencia o sinal para não disparar _on_busca_changed durante a limpeza
            self.busca_input.blockSignals(True)
            self.busca_input.clear()
            self.busca_input.blockSignals(False)
        self._set_modo_sala()
        self.update_patrimonios_table()

    # ------------------------------------------------------------------
    # Tabela de patrimônios — modo sala
    # ------------------------------------------------------------------

    def _set_modo_sala(self):
        """Configura a tabela de patrimônios para o modo de visualização por sala."""
        self.patrimonio_table.setColumnHidden(12, True)

    def _set_modo_busca(self):
        """Configura a tabela de patrimônios para o modo de busca global."""
        self.patrimonio_table.setColumnHidden(12, False)

    def update_filter_mode(self):
        """Atualiza o modo de filtro com base na seleção do ComboBox."""
        index = self.filter_combo.currentIndex()
        if index == 0:
            self.filter_mode = "all"
        elif index == 1:
            self.filter_mode = "encontrados"
        elif index == 2:
            self.filter_mode = "nao_encontrados"
        # Aplica apenas se não estiver em modo de busca global
        if not self.busca_input.text():
            self.update_patrimonios_table()

    def update_patrimonios_table(self):
        """Atualiza a tabela de patrimônios com base na sala selecionada e no filtro."""
        selected_items = self.sala_table.selectedItems()
        if not selected_items:
            self.patrimonio_table.setRowCount(0)
            self.total_label.setText("Total de Patrimônios: 0")
            self.encontrados_label.setText("Patrimônios Encontrados: 0")
            return

        # Obter o sala_id do item selecionado
        sala_id = selected_items[0].data(Qt.UserRole)
        self.patrimonio_table.setRowCount(0)

        # Buscar todos os patrimônios da sala
        patrimonios = self.db_manager.get_patrimonios_by_sala(sala_id)

        # Filtrar com base no modo de filtro
        # get_patrimonios_by_sala retorna 13 campos:
        #   [0..9] exibição, [-3] encontrado, [-2] sala_id_original, [-1] sala_original_nome
        filtered_patrimonios = []
        for patrimonio in patrimonios:
            encontrado = patrimonio[-3]
            if self.filter_mode == "all":
                filtered_patrimonios.append(patrimonio)
            elif self.filter_mode == "encontrados" and encontrado == 1:
                filtered_patrimonios.append(patrimonio)
            elif self.filter_mode == "nao_encontrados" and encontrado == 0:
                filtered_patrimonios.append(patrimonio)

        self.patrimonio_table.setRowCount(len(filtered_patrimonios))

        # Estatísticas sempre referentes ao total da sala, independente do filtro ativo
        total_patrimonios = len(patrimonios)
        encontrados = sum(1 for r in patrimonios if r[-3] == 1)
        self.total_label.setText(f"Total de Patrimônios: {total_patrimonios}")
        self.encontrados_label.setText(f"Patrimônios Encontrados: {encontrados}")

        for row_idx, row_data in enumerate(filtered_patrimonios):
            is_divergent = row_data[-2] is not None and row_data[-2] != sala_id
            highlight_color = (QColor(255, 255, 0) if is_divergent else
                               QColor(144, 238, 144) if row_data[-3] == 1 else None)

            for col_idx, value in enumerate(row_data[:-3]):  # 10 campos de exibição
                item = QTableWidgetItem(str(value or ""))
                if highlight_color:
                    item.setBackground(QBrush(highlight_color))
                self.patrimonio_table.setItem(row_idx, col_idx, item)

            # Coluna Encontrado (índice 10)
            encontrado_text = "Sim" if row_data[-3] == 1 else "Não"
            item = QTableWidgetItem(encontrado_text)
            if highlight_color:
                item.setBackground(QBrush(highlight_color))
            self.patrimonio_table.setItem(row_idx, 10, item)

            # Coluna Sala Original (índice 11) — nome resolvido via JOIN
            item = QTableWidgetItem(row_data[-1] or "")
            if highlight_color:
                item.setBackground(QBrush(highlight_color))
            self.patrimonio_table.setItem(row_idx, 11, item)

            # Coluna Sala Atual (índice 12) — vazia no modo sala
            self.patrimonio_table.setItem(row_idx, 12, QTableWidgetItem(""))

    # ------------------------------------------------------------------
    # Busca global por número de patrimônio
    # ------------------------------------------------------------------

    def _on_busca_changed(self, texto):
        """Reage à mudança no campo de busca global."""
        texto = texto.strip()
        if texto:
            self._set_modo_busca()
            self.sala_table.clearSelection()
            self._executar_busca(texto)
        else:
            self._set_modo_sala()
            self.patrimonio_table.setRowCount(0)
            self.total_label.setText("Total de Patrimônios: 0")
            self.encontrados_label.setText("Patrimônios Encontrados: 0")

    def _executar_busca(self, numero):
        """Preenche a tabela de patrimônios com resultados da busca global."""
        # search_patrimonio retorna 14 campos:
        #   [0..9] exibição, [10] encontrado, [11] sala_id_original,
        #   [12] sala_original_nome, [13] sala_atual_nome
        resultados = self.db_manager.search_patrimonio(numero)

        filtered = []
        for row in resultados:
            encontrado = row[10]
            if self.filter_mode == "all":
                filtered.append(row)
            elif self.filter_mode == "encontrados" and encontrado == 1:
                filtered.append(row)
            elif self.filter_mode == "nao_encontrados" and encontrado == 0:
                filtered.append(row)

        self.patrimonio_table.setRowCount(len(filtered))

        # Estatísticas sempre referentes ao total encontrado pela busca, independente do filtro ativo
        total = len(resultados)
        encontrados = sum(1 for r in resultados if r[10] == 1)
        self.total_label.setText(f"Total de Patrimônios: {total}")
        self.encontrados_label.setText(f"Patrimônios Encontrados: {encontrados}")

        for row_idx, row_data in enumerate(filtered):
            encontrado = row_data[10]
            sala_id_original = row_data[11]
            sala_atual_nome = row_data[13]
            sala_original_nome = row_data[12]

            # Divergente = encontrado em sala diferente da original
            is_divergent = (
                encontrado == 1
                and sala_id_original is not None
                and sala_atual_nome != sala_original_nome
            )
            highlight_color = (QColor(255, 255, 0) if is_divergent else
                               QColor(144, 238, 144) if encontrado == 1 else None)

            for col_idx, value in enumerate(row_data[:10]):  # 10 campos de exibição
                item = QTableWidgetItem(str(value or ""))
                if highlight_color:
                    item.setBackground(QBrush(highlight_color))
                self.patrimonio_table.setItem(row_idx, col_idx, item)

            # Coluna Encontrado (10)
            item = QTableWidgetItem("Sim" if encontrado == 1 else "Não")
            if highlight_color:
                item.setBackground(QBrush(highlight_color))
            self.patrimonio_table.setItem(row_idx, 10, item)

            # Coluna Sala Original (11)
            item = QTableWidgetItem(sala_original_nome or "")
            if highlight_color:
                item.setBackground(QBrush(highlight_color))
            self.patrimonio_table.setItem(row_idx, 11, item)

            # Coluna Sala Atual (12)
            item = QTableWidgetItem(sala_atual_nome or "")
            if highlight_color:
                item.setBackground(QBrush(highlight_color))
            self.patrimonio_table.setItem(row_idx, 12, item)

    # ------------------------------------------------------------------
    # Relatório
    # ------------------------------------------------------------------

    def start_report_generation(self):
        """Inicia a geração de relatório em thread separada."""
        self.report_button.setEnabled(False)
        self.report_button.setText("Gerando...")
        self._report_worker = self.report_generator.create_worker()
        self._report_worker.finished.connect(self._on_report_done)
        self._report_worker.error.connect(self._on_report_error)
        self._report_worker.start()

    def _on_report_done(self, base_dir: str):
        self.report_button.setEnabled(True)
        self.report_button.setText("Gerar Relatório")
        QMessageBox.information(self, "Relatório", f"Relatório gerado em:\n{base_dir}")
        logger.info("Relatório gerado com sucesso em %s", base_dir)

    def _on_report_error(self, message: str):
        self.report_button.setEnabled(True)
        self.report_button.setText("Gerar Relatório")
        QMessageBox.critical(self, "Erro", f"Erro ao gerar relatório:\n{message}")
        logger.error("Falha na geração do relatório: %s", message)

    # ------------------------------------------------------------------
    # Janela de escaneamento
    # ------------------------------------------------------------------

    def open_scan_window(self):
        """Abre a janela de escaneamento, se uma sala estiver selecionada."""
        selected_items = self.sala_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Erro", "Por favor, selecione uma sala antes de escanear.")
            return

        sala_id = selected_items[0].data(Qt.UserRole)
        self.hide()
        from scan_window import ScanWindow
        self.scan_window = ScanWindow(self.db_manager, self, sala_id)
        self.scan_window.show()
        self.showMaximized()

    def refresh_after_scan(self):
        """Atualiza tabelas após retornar da janela de escaneamento."""
        self.populate_sala_table(self.filter_input.text().strip())
        self.update_patrimonios_table()

    # ------------------------------------------------------------------
    # Carregar arquivo CSV
    # ------------------------------------------------------------------

    def carregar_arquivo(self):
        """Abre um seletor de arquivo para carregar um CSV exportado do SUAP."""
        caminho, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar arquivo CSV do SUAP",
            "",
            "Arquivos CSV (*.csv);;Todos os arquivos (*)",
        )
        if not caminho:
            return

        confirmacao = QMessageBox.warning(
            self,
            "Confirmar carregamento",
            "Atenção: carregar um novo arquivo apagará todo o progresso atual "
            "(patrimônios escaneados e marcações de encontrado).\n\n"
            "Deseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmacao != QMessageBox.Yes:
            return

        self.load_button.setEnabled(False)
        self.load_button.setText("Carregando...")

        self._load_worker = LoadWorker(self.db_manager, caminho)
        self._load_worker.finished.connect(self._on_load_done)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _on_load_done(self, n_patrimonios: int, n_salas: int):
        self.load_button.setEnabled(True)
        self.load_button.setText("Carregar Arquivo")
        self.busca_input.clear()
        self.populate_sala_table("")
        self.patrimonio_table.setRowCount(0)
        self.total_label.setText("Total de Patrimônios: 0")
        self.encontrados_label.setText("Patrimônios Encontrados: 0")
        QMessageBox.information(
            self,
            "Arquivo carregado",
            f"Dados importados com sucesso.\n\n"
            f"Patrimônios: {n_patrimonios}\nSalas: {n_salas}",
        )

    def _on_load_error(self, message: str):
        self.load_button.setEnabled(True)
        self.load_button.setText("Carregar Arquivo")
        QMessageBox.critical(self, "Erro ao carregar arquivo", message)

    # ------------------------------------------------------------------
    # Fechamento
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        """Evento de fechamento da janela principal."""
        event.accept()
