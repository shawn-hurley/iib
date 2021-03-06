# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os

from flask import Flask
from flask.logging import default_handler
from flask_login import LoginManager
from flask_migrate import Migrate
import kombu.exceptions
from werkzeug.exceptions import default_exceptions

from iib.exceptions import ConfigError, IIBError, ValidationError
from iib.web import db
from iib.web.api_v1 import api_v1
from iib.web.auth import user_loader, load_user_from_request
from iib.web.docs import docs
from iib.web.errors import json_error

# Import the models here so that Alembic will be guaranteed to detect them
import iib.web.models  # noqa: F401


def load_config(app):
    """
    Determine the correct configuration to use and apply it.

    :param flask.Flask app: a Flask application object
    """
    config_file = None
    if os.getenv('IIB_DEV', '').lower() == 'true':
        default_config_obj = 'iib.web.config.DevelopmentConfig'
    else:
        default_config_obj = 'iib.web.config.ProductionConfig'
        config_file = '/etc/iib/settings.py'
    app.config.from_object(default_config_obj)

    if config_file and os.path.isfile(config_file):
        app.config.from_pyfile(config_file)


def validate_api_config(config):
    """
    Determine if the configuration is valid.

    :param dict config: the dict containing the IIB REST API config
    :raises ConfigError: if the config is invalid
    """
    if config['IIB_GREENWAVE_CONFIG']:
        defined_queue_names = set(config['IIB_USER_TO_QUEUE'].values())
        invalid_greenwave_queues = set(config['IIB_GREENWAVE_CONFIG'].keys()) - defined_queue_names
        # The queue_name `None` is the configuration for the default Celery queue
        invalid_greenwave_queues.discard(None)
        if invalid_greenwave_queues:
            raise ConfigError(
                f'The following queues are invalid in "IIB_GREENWAVE_CONFIG"'
                f': {", ".join(invalid_greenwave_queues)}'
            )

        required_params = {'decision_context', 'product_version', 'subject_type'}
        for queue_name, greenwave_config in config['IIB_GREENWAVE_CONFIG'].items():
            defined_params = set(greenwave_config.keys())

            missing_params = required_params - defined_params
            if missing_params:
                raise ConfigError(
                    f'Missing required params {", ".join(missing_params)} for queue {queue_name} '
                    'in "IIB_GREENWAVE_CONFIG"'
                )

            invalid_params = defined_params - required_params
            if invalid_params:
                raise ConfigError(
                    f'Invalid params {", ".join(invalid_params)} for queue {queue_name} '
                    'in "IIB_GREENWAVE_CONFIG"'
                )

            if greenwave_config['subject_type'] != 'koji_build':
                raise ConfigError(
                    'IIB only supports gating for subject_type "koji_build". Invalid subject_type '
                    f'{greenwave_config["subject_type"]} defined for queue '
                    f'{queue_name} in "IIB_GREENWAVE_CONFIG"'
                )


# See app factory pattern:
#   http://flask.pocoo.org/docs/0.12/patterns/appfactories/
def create_app(config_obj=None):  # pragma: no cover
    """
    Create a Flask application object.

    :param str config_obj: the path to the configuration object to use instead of calling
        load_config
    :return: a Flask application object
    :rtype: flask.Flask
    """
    app = Flask(__name__)
    if config_obj:
        app.config.from_object(config_obj)
    else:
        load_config(app)

    # Validate the config
    validate_api_config(app.config)

    # Configure logging
    default_handler.setFormatter(
        logging.Formatter(fmt=app.config['IIB_LOG_FORMAT'], datefmt='%Y-%m-%d %H:%M:%S')
    )
    app.logger.setLevel(app.config['IIB_LOG_LEVEL'])
    for logger_name in app.config['IIB_ADDITIONAL_LOGGERS']:
        logger = logging.getLogger(logger_name)
        logger.setLevel(app.config['IIB_LOG_LEVEL'])
        # Add the Flask handler that streams to WSGI stderr
        logger.addHandler(default_handler)

    # Initialize the database
    db.init_app(app)
    # Initialize the database migrations
    migrations_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'migrations')
    Migrate(app, db, directory=migrations_dir)
    # Initialize Flask Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.user_loader(user_loader)
    login_manager.request_loader(load_user_from_request)

    app.register_blueprint(docs)
    app.register_blueprint(api_v1, url_prefix='/api/v1')
    for code in default_exceptions.keys():
        app.register_error_handler(code, json_error)
    app.register_error_handler(IIBError, json_error)
    app.register_error_handler(ValidationError, json_error)
    app.register_error_handler(kombu.exceptions.KombuError, json_error)

    return app
