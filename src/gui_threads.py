from PySide6.QtCore import QThread, Signal
import server_connector
import create_database

class CreateDatabaseThread(QThread):
    def run(self):
        create_database.main()

class SubmitButtonThread(QThread):
    responseSignal = Signal(str)
    errorSignal = Signal()

    def __init__(self, user_question, parent=None, callback=None):
        super(SubmitButtonThread, self).__init__(parent)
        self.user_question = user_question
        self.callback = callback
        self.cancel_stream = False

    def request_cancellation(self):
        self.cancel_stream = True
        print("gui_thread cancel_stream = true")

    def run(self):
        try:
            response = server_connector.ask_local_chatgpt(self.user_question, self.cancel_stream)
            for response_chunk in response:
                if self.cancel_stream:
                    break
                    print("gui_thread break")
                self.responseSignal.emit(response_chunk)
            if self.callback:
                self.callback()
        except Exception as err:
            self.errorSignal.emit()
            print(err)