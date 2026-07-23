import logging

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QApplication, QMessageBox
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

logger = logging.getLogger(__name__)

class ScanWindow(QDialog):
    def __init__(self, db_manager, parent=None, sala_id=None):
        super().__init__(parent)
        self.setWindowTitle("Escanear Código de Barras")
        self.db_manager = db_manager
        self.parent = parent
        self.sala_id = sala_id
        self.is_processing = False

        # Contadores da sessão atual
        self._encontrados_sessao = 0
        self._nao_cadastrados_sessao = 0
        self._duplicados_sessao = 0

        self.setWindowModality(Qt.ApplicationModal)

        screen = QApplication.primaryScreen().size()
        width = int(screen.width() * 0.8)
        height = int(screen.height() * 0.8)
        self.resize(width, height)
        self.move(int((screen.width() - width) / 2), int((screen.height() - height) / 2))

        layout = QVBoxLayout()
        layout.addStretch(1)

        label = QLabel("Escaneie o número do patrimônio:")
        label.setFont(QFont("Arial", 16))
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        sala_nome = self.get_sala_nome()
        self.sala_label = QLabel(f"Sala: {sala_nome}")
        self.sala_label.setFont(QFont("Arial", 16))
        self.sala_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.sala_label, alignment=Qt.AlignCenter)

        self.input = QLineEdit()
        self.input.setFont(QFont("Arial", 16))
        self.input.setMaximumWidth(400)
        self.input.returnPressed.connect(self.handle_return_pressed)
        layout.addWidget(self.input, alignment=Qt.AlignCenter)

        self.feedback_label = QLabel("")
        self.feedback_label.setFont(QFont("Arial", 14))
        self.feedback_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.feedback_label)

        close_button = QPushButton("Fechar")
        close_button.setFont(QFont("Arial", 12))
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, alignment=Qt.AlignCenter)

        layout.addStretch(1)
        self.setLayout(layout)
        self.input.setFocus()

    def get_sala_nome(self):
        """Obtém o nome da sala com base no sala_id."""
        if self.sala_id:
            self.db_manager.cursor.execute("SELECT sala FROM salas WHERE id = ?", (self.sala_id,))
            result = self.db_manager.cursor.fetchone()
            return result[0] if result else "Desconhecida"
        return "Nenhuma sala selecionada"

    def _set_feedback(self, texto, cor):
        """Exibe mensagem de feedback com a cor indicada."""
        self.feedback_label.setText(texto)
        self.feedback_label.setStyleSheet(f"color: {cor}; font-weight: bold;")

    def handle_return_pressed(self):
        """Manipula o sinal returnPressed para evitar múltiplas chamadas."""
        if not self.is_processing:
            self.is_processing = True
            self.input.setEnabled(False)
            QTimer.singleShot(0, self.process_scan)
            QTimer.singleShot(200, self.reset_processing)

    def reset_processing(self):
        """Redefine a flag de processamento e reativa a entrada."""
        self.is_processing = False
        self.input.setEnabled(True)
        self.input.setFocus()
        self.activateWindow()
        self.raise_()

    def process_scan(self):
        """Processa o escaneamento e mantém a janela aberta para escaneamento contínuo."""
        numero = self.input.text().strip()
        logger.debug("Processando escaneamento: %s", numero)

        if not numero:
            self._set_feedback("Nenhum código escaneado.", "gray")
            self.input.clear()
            return

        if not self.sala_id:
            self._set_feedback("Nenhuma sala selecionada.", "gray")
            self.input.clear()
            return

        # Verificar status atual antes de marcar
        status = self.db_manager.get_patrimonio_status(numero)

        if status is None:
            # Patrimônio não cadastrado no banco
            self.db_manager.record_unfound_patrimonio(numero, self.sala_id)
            self._nao_cadastrados_sessao += 1
            self._set_feedback(
                f"Patrimônio {numero} não cadastrado no sistema — registrado.",
                "rgb(180, 0, 0)",
            )
            logger.info("Patrimônio não cadastrado escaneado: %s", numero)
        elif status[0] == 1:
            # Já estava marcado como encontrado anteriormente
            self._duplicados_sessao += 1
            self._set_feedback(
                f"Patrimônio {numero} já havia sido marcado como encontrado.",
                "rgb(180, 100, 0)",
            )
            logger.info("Escaneamento duplicado: %s", numero)
        else:
            # Marcar como encontrado
            self.db_manager.mark_patrimonio_encontrado(numero, self.sala_id)
            self._encontrados_sessao += 1
            sala_nome = self.sala_label.text().replace("Sala: ", "")
            self._set_feedback(
                f"Patrimônio {numero} encontrado na sala {sala_nome}.",
                "rgb(0, 130, 0)",
            )
            logger.info("Patrimônio encontrado: %s", numero)
            if self.parent:
                self.parent.update_patrimonios_table()

        self.input.clear()

    def keyPressEvent(self, event):
        """Impede que a tecla Enter ou Esc feche a janela."""
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            if not self.is_processing:
                self.handle_return_pressed()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Exibe resumo da sessão e restaura a janela principal."""
        # Calcular itens ainda não encontrados na sala
        pendentes = 0
        if self.sala_id:
            try:
                self.db_manager.cursor.execute(
                    "SELECT COUNT(*) FROM patrimonios WHERE sala_id = ? AND encontrado = 0",
                    (self.sala_id,)
                )
                resultado = self.db_manager.cursor.fetchone()
                pendentes = resultado[0] if resultado else 0
            except Exception as e:
                logger.error("Erro ao calcular pendentes para resumo: %s", e)

        total_sessao = self._encontrados_sessao + self._nao_cadastrados_sessao + self._duplicados_sessao
        if total_sessao > 0:
            QMessageBox.information(
                self,
                "Resumo da Sessão",
                f"Resumo dos escaneamentos desta sessão:\n\n"
                f"✔  Encontrados agora:       {self._encontrados_sessao}\n"
                f"⚠  Já marcados anteriormente: {self._duplicados_sessao}\n"
                f"✘  Não cadastrados:         {self._nao_cadastrados_sessao}\n\n"
                f"Patrimônios ainda pendentes na sala: {pendentes}",
            )

        try:
            if self.parent is not None:
                self.parent.refresh_after_scan()
                self.parent.showMaximized()
        except Exception as e:
            logger.error("Erro ao restaurar a janela principal: %s", e)
        event.accept()
