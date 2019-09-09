import logging
from flask import Flask, jsonify, request
from threading import Thread


class Api:
    def __init__(self, port, add_transaction, get_transactions):
        self.port = port
        self.add_transaction = add_transaction
        self.get_transactions = get_transactions

    def setup_routes(self, app):
        @app.route("/transaction", methods=['POST'])
        def add_transaction():
            self.add_transaction(request.get_json())
            return jsonify({"msg": "OK"})

    def setup_logging(self):
        logger = logging.getLogger("werkzeug")
        logger.disabled = True
        
    def run_app(self):
        app = Flask(__name__)
        self.setup_routes(app)
        self.setup_logging()
        app.run(port=self.port, use_reloader=False)
        
    def run(self):
        thread = Thread(target=self.run_app, daemon=True)
        thread.start()
        print(f"Flask server listening on port {self.port}")
