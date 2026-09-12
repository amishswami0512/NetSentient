import logging
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from config import Config
from models.schemas import APIError
from routes.classify import classify_bp
from routes.demo import demo_bp
from routes.health import health_bp
from routes.simulation import simulation_bp
from routes.traffic import traffic_bp


def create_app() -> Flask:
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    app = Flask(__name__, static_folder=str(frontend_dir), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH_BYTES

    logging.basicConfig(level=logging.INFO)

    CORS(app, origins=Config.ALLOWED_ORIGINS)

    app.register_blueprint(health_bp)
    app.register_blueprint(traffic_bp)
    app.register_blueprint(classify_bp)
    app.register_blueprint(simulation_bp)
    app.register_blueprint(demo_bp)

    @app.get("/")
    def serve_frontend():
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return jsonify({"error": {"code": err.code, "message": err.message}}), err.status_code

    @app.errorhandler(404)
    def handle_not_found(_err):
        return jsonify(
            {"error": {"code": "NOT_FOUND", "message": "The requested resource was not found."}}
        ), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return jsonify(
            {
                "error": {
                    "code": "METHOD_NOT_ALLOWED",
                    "message": "This HTTP method is not supported for this endpoint.",
                }
            }
        ), 405

    @app.errorhandler(413)
    def handle_payload_too_large(_err):
        return jsonify(
            {"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}}
        ), 413

    @app.errorhandler(Exception)
    def handle_unexpected_error(err: Exception):
        app.logger.exception("Unexpected error: %s", err)
        return jsonify(
            {
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected server error occurred.",
                }
            }
        ), 500

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
