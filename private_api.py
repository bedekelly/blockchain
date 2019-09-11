import logging
import asyncio
from flask import Flask, jsonify, request
from threading import Thread


class Api:
    def __init__(self, port, miner):
        self.port = port
        self.miner = miner

    def setup_routes(self, app):
        @app.route("/transaction", methods=["POST"])
        def add_transaction():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            data = request.get_json()
            return jsonify(self.miner.add_outbound_transaction(data))

        @app.route("/unspent")
        def get_unspent():
            return jsonify(unspent=self.miner.unspent())

        @app.route("/balances")
        def get_balances():
            return jsonify(balances=self.miner.balances())

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
