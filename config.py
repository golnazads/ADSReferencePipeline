
# -*- coding: utf-8 -*-

LOG_STDOUT = True

REFERENCE_PIPELINE_ADSWS_API_TOKEN = 'this is a secret api token!'
#REFERENCE_PIPELINE_SERVICE_TEXT_URL = 'https://dev.adsabs.harvard.edu/v1/reference/text'
REFERENCE_PIPELINE_SERVICE_TEXT_URL = 'http://0.0.0.0:5000/text'

# db config
SQLALCHEMY_URL = 'url to db'
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ECHO = False


# possible values: WARN, INFO, DEBUG
LOGGING_LEVEL = 'DEBUG'


# celery config
CELERY_INCLUDE = ['adsrefpipe.tasks']
CELERY_BROKER = 'pyamqp://'