import warnings
# Suprimir todos os DeprecationWarning antes de qualquer importação
warnings.filterwarnings("ignore", category=DeprecationWarning)

import logging

from PyQt5.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QWidget, QHBoxLayout,
    QSpacerItem, QSizePolicy, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLineEdit, QComboBox, QMessageBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QBrush, QColor
from report_generator import ReportGenerator, ReportWorker

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, db_manager):
        super().__init__()
        self.setWindowTitle("SUAP-CP - Conferência de Patrimônio")
        self.db_manager = db_manager
        self.filter_mode = "all"  # Modo de filtro inicial: todos
        self.report_generator = ReportGenerator(db_manager)
        self._report_worker: ReportWorker | None = None

        # Layout principal
        layout = QVBoxLayout()
        
        # Espaçador superior reduzido
        layout.addItem(QSpacerItem(20, 10, QSizePolicy.Minimum, QSizePolicy.Fixed))
        
        # Título
        label = QLabel("Bem-vindo ao SUAP-CP!", self)
        label.setFont(QFont("Arial", 16))
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        
        # Layout horizontal para botões
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
        
        # Campo de filtro para salas
        self.filter_input = QLineEdit()
        self.filter_input.setFont(QFont("Arial", 12))
        self.filter_input.setPlaceholderText("Filtrar salas...")
        self.filter_input.textChanged.connect(self.filter_salas)
        layout.addWidget(self.filter_input)
        
        # Tabela para selecionar salas
        self.sala_table = QTableWidget(self)
        self.sala_table.setColumnCount(1)
        self.sala_table.setHorizontalHeaderLabels(["Nome da Sala"])
        self.sala_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sala_table.setFont(QFont("Arial", 10))
        self.sala_table.setSelectionMode(QTableWidget.SingleSelection)
        self.sala_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sala_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Impedir edição
        self.populate_sala_table("")  # Inicializar sem filtro
        self.sala_table.clicked.connect(self.update_patrimonios_table)
        layout.addWidget(self.sala_table, stretch=1)  # Ocupa metade do espaço
        
        # ComboBox para filtro de encontrado
        self.filter_combo = QComboBox()
        self.filter_combo.setFont(QFont("Arial", 12))
        self.filter_combo.addItems(["Todos", "Encontrados", "Não Encontrados"])
        self.filter_combo.currentIndexChanged.connect(self.update_filter_mode)
        layout.addWidget(self.filter_combo)
        
        # Tabela para exibir patrimônios
        self.patrimonio_table = QTableWidget(self)
        self.patrimonio_table.setColumnCount(12)
        self.patrimonio_table.setHorizontalHeaderLabels([
            "Número", "Status", "ED", "Descrição", "Rótulos", "Carga Atual",
            "Setor Responsável", "Campus Carga", "Número de Série", "Estado Conservação",
            "Encontrado", "Sala Original"
        ])
        self.patrimonio_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.patrimonio_table.setFont(QFont("Arial", 10))
        self.patrimonio_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Impedir edição
        layout.addWidget(self.patrimonio_table, stretch=1)  # Ocupa metade do espaço
        
        # Labels para estatísticas
        self.total_label = QLabel("Total de Patrimônios: 0")
        self.total_label.setFont(QFont("Arial", 12))
        self.total_label.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.total_label)
        
        self.encontrados_label = QLabel("Patrimônios Encontrados: 0")
        self.encontrados_label.setFont(QFont("Arial", 12))
        self.encontrados_label.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.encontrados_label)
        
        # Espaçador inferior reduzido
        layout.addItem(QSpacerItem(20, 10, QSizePolicy.Minimum, QSizePolicy.Fixed))
        
        # Container
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def populate_sala_table(self, filter_text):
        """Popula a QTableWidget com salas, aplicando o filtro especificado."""
        salas = self.db_manager.get_all_salas()
        # Filtrar salas com base no texto (sem distinção entre maiúsculas e minúsculas)
        filtered_salas = [
            (sala_id, sala_nome) for sala_id, sala_nome in salas
            if filter_text.lower() in sala_nome.lower()
        ]
        self.sala_table.setRowCount(len(filtered_salas))
        for row_idx, (sala_id, sala_nome) in enumerate(filtered_salas):
            item = QTableWidgetItem(sala_nome)
            item.setData(Qt.UserRole, sala_id)  # Armazenar sala_id como dado associado
            self.sala_table.setItem(row_idx, 0, item)

    def filter_salas(self):
        """Atualiza a tabela de salas com base no texto do filtro."""
        filter_text = self.filter_input.text().strip()
        self.populate_sala_table(filter_text)

    def update_filter_mode(self):
        """Atualiza o modo de filtro com base na seleção do ComboBox."""
        index = self.filter_combo.currentIndex()
        if index == 0:
            self.filter_mode = "all"
        elif index == 1:
            self.filter_mode = "encontrados"
        elif index == 2:
            self.filter_mode = "nao_encontrados"
        self.update_patrimonios_table()

    def update_patrimonios_table(self):
        """Atualiza a tabela de patrimônios com base na sala selecionada e no filtro de encontrado."""
        selected_items = self.sala_table.selectedItems()
        if not selected_items:
            self.patrimonio_table.setRowCount(0)
            self.total_label.setText("Total de Patrimônios: 0")
            self.encontrados_label.setText("Patrimônios Encontrados: 0")
            return
        
        # Obter o sala_id do item selecionado
        sala_id = selected_items[0].data(Qt.UserRole)
        
        # Limpar tabela de patrimônios
        self.patrimonio_table.setRowCount(0)
        
        # Buscar todos os patrimônios da sala
        patrimonios = self.db_manager.get_patrimonios_by_sala(sala_id)
        
        # Filtrar patrimônios com base no modo de filtro
        # get_patrimonios_by_sala retorna 13 campos:
        # [0..9] dados de exibição, [-3] encontrado, [-2] sala_id_original, [-1] sala_original_nome
        filtered_patrimonios = []
        for patrimonio in patrimonios:
            encontrado = patrimonio[-3]
            if self.filter_mode == "all":
                filtered_patrimonios.append(patrimonio)
            elif self.filter_mode == "encontrados" and encontrado == 1:
                filtered_patrimonios.append(patrimonio)
            elif self.filter_mode == "nao_encontrados" and encontrado == 0:
                filtered_patrimonios.append(patrimonio)

        # Atualizar tabela com os patrimônios filtrados
        self.patrimonio_table.setRowCount(len(filtered_patrimonios))

        # Calcular estatísticas
        total_patrimonios = len(filtered_patrimonios)
        encontrados = sum(1 for row_data in filtered_patrimonios if row_data[-3] == 1)

        # Atualizar labels
        self.total_label.setText(f"Total de Patrimônios: {total_patrimonios}")
        self.encontrados_label.setText(f"Patrimônios Encontrados: {encontrados}")

        # Preencher tabela
        for row_idx, row_data in enumerate(filtered_patrimonios):
            is_divergent = row_data[-2] is not None and row_data[-2] != sala_id
            highlight_color = (QColor(255, 255, 0) if is_divergent else
                               QColor(144, 238, 144) if row_data[-3] == 1 else None)

            for col_idx, value in enumerate(row_data[:-3]):  # 10 campos de exibição
                item = QTableWidgetItem(str(value or ""))
                if highlight_color:
                    item.setBackground(QBrush(highlight_color))
                self.patrimonio_table.setItem(row_idx, col_idx, item)

            # Coluna Encontrado
            encontrado_text = "Sim" if row_data[-3] == 1 else "Não"
            item = QTableWidgetItem(encontrado_text)
            if highlight_color:
                item.setBackground(QBrush(highlight_color))
            self.patrimonio_table.setItem(row_idx, 10, item)

            # Coluna Sala Original — nome já resolvido via JOIN no banco
            item = QTableWidgetItem(row_data[-1] or "")
            if highlight_color:
                item.setBackground(QBrush(highlight_color))
            self.patrimonio_table.setItem(row_idx, 11, item)

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

    def open_scan_window(self):
        """Abre a janela de escaneamento de código de barras como diálogo modal, se uma sala estiver selecionada."""
        selected_items = self.sala_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Erro", "Por favor, selecione uma sala antes de escanear.")
            return
        
        sala_id = selected_items[0].data(Qt.UserRole)
        self.hide()
        from scan_window import ScanWindow
        self.scan_window = ScanWindow(self.db_manager, self, sala_id)
        self.scan_window.show()  # Abrir a janela de escaneamento
        self.showMaximized()  # Restaurar a janela principal após fechar

    def closeEvent(self, event):
        """Evento de fechamento da janela principal."""
        event.accept()