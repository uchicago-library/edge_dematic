#!/usr/bin/python3
# Run with gunicorn --workers=2 --reload --bind=0.0.0.0:8080 --error-logfile=/var/log/edge/app.log --access-logfile=/var/log/edge/app_access.log --log-level=info app:app


import sys
from time import *
import datetime
from traceback import *
import requests
from lxml import etree
from io import StringIO, BytesIO
import logging
from flask import Flask, make_response, request, jsonify
import re
import json
import smtplib
from email.message import EmailMessage


class main_class():
    # host = 'test'
    # host = 'migration'
    host = 'prod'
    x = {'prod': '-', 'test': '-test-', 'migration': '-migration-'}[host]
    edge = {'url': f'https://my{x}edge-server.example.com',
            'config': '', # edge config key goes here. Comes from edge common
            'params': {'limit': 2147483647, 'timeout': 10},
            'headers': {'content-type': 'application/xml',
                        'charset': 'UTF-8',
                        'authorization': ''}} # edge token generated for
                                               # edge user
        
    okapi = {'url': f'https://my{x}okapi-server.example.com',
             'tenant': 'tenant_name',
             'username': 'service username',
             'password': 'service password',
             'params': {'limit': 2147483647, 'timeout': 10},
             'headers': {"content-type": "application/json",
                         "x-okapi-tenant": 'tennant_name',
                         'x-okapi-token': ''}} # okapi token generated from
                                               # authorization endpoint
             
    def __init__(self):
        self.endpoint = None
        self.recent_items = []
        self.null_items = []
        self.sender = '' # sender email
        self.librarians = [''] # email for librarians for null barcode
        self.sysadmins = [''] # email for errors and other info
        self.subject = None
        self.message = None
        self.stack_trace = True

        
def main():
    m = main_class()
    return m


app = Flask(__name__)
log = app.logger
m = main_class()


if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    log.handlers = gunicorn_logger.handlers
    log.setLevel(gunicorn_logger.level)


@app.errorhandler(Exception)
def basic_error(e):
    if e.code == 404 and request.remote_addr[:-3] == 'xx.xx.xxx':
        msg = f"An ITS security probe occured (error code {e.code}), " \
            f"initiated from {request.remote_addr}.\n"
        log.error(msg)
        return make_response(msg, 404)
    else:         
        msg = f"An error occurred.\n{format_exc()}"
        log.error(msg)
        m.subject = "An error occurred in middleware app"
        m.message = msg
        send_email(m, m.sysadmins)
        return make_response(msg, 500)


@app.route('/asrService/asr/lookupNewAsrItems/10001')
@app.route('/asrService/asr/lookupNewAsrItems/10001,ASR')
def lookup_new_items():
    # log.info(f"{request.method} {request.url}")
    m = main_class()
    check_items_for_null_barcodes(m)
    purge_items_with_null_barcodes(m)
    m.endpoint = '/asrService/asr/lookupNewAsrItems'
    r = requests.get(m.edge['url'] + m.endpoint + m.edge['config'],
                     headers = m.edge['headers'],
                      params = m.edge['params'])
    if not r.ok:
        return make_response(r.reason, r.status_code)
    doc = etree.XML(r.content)
    l = [{e.tag:e.text for e in item} for item in doc]
    if l:
        count = 0
        x = etree.Element('asrItems')
        y = etree.Element('asrItems')
        for d in l:
            z = etree.Element('asrItem')
            s = etree.SubElement(z, 'itemNumber')
            if 'itemNumber' in d and d['itemNumber']:
                s.text = d['itemNumber']
            s = etree.SubElement(z, 'author')
            if 'author' in d and d['author']:
                s.text = d['author']
            s = etree.SubElement(z, 'title')
            if 'title' in d and d['title']:
                s.text = d['title']
            s = etree.SubElement(z, 'callNumber')
            if 'callNumber' in d and d['callNumber']:
                s.text = d['callNumber']
            y.append(z)
            count += 1
        x.append(y)
        x = etree.tostring(x, encoding='UTF-8', xml_declaration=True,
                           standalone=True)
        log.info(f"Newly accessioned items ({count}):\n{x}\n")
    else:
        x = etree.Element('asrResponse')
        etree.SubElement(x, 'code').text = '007'
        etree.SubElement(x, 'message').text = 'Item not found'
        x = etree.tostring(x, encoding='UTF-8', xml_declaration=True,
                           standalone=True)
    response = make_response(x, r.status_code)
    response.headers = {'Content-Type': 'application/xml'}
    return response


@app.route('/asrService/asr/lookupAsrRequests/10001')
@app.route('/asrService/asr/lookupAsrRequests/10001,ASR')
def lookup_new_requests():
    m = main_class()
    stat_dict = {'Open - Not yet filled': '1'}
    m.endpoint = '/asrService/asr/lookupAsrRequests'
    r = requests.get(m.edge['url'] + m.endpoint + m.edge['config'],
                     headers = m.edge['headers'],
                      params = m.edge['params'])
    if not r.ok:
        log.debug(f"REASON   {r.reason}")
        return make_response(r.reason, r.status_code)
    doc = etree.XML(r.content)
    l = [{e.tag:e.text for e in item} for item in doc]
    if l:
        count = 0
        x = etree.Element('asrRequests')
        y = etree.Element('asrRequests')
        for d in l:
            z = etree.Element('asrRequest')
            s = etree.SubElement(z, 'holdId')
            if 'holdId' in d and d['holdId']: s.text = d['holdId']
            s = etree.SubElement(z, 'itemBarcode')
            if 'itemBarcode' in d and d['itemBarcode']:
                s.text = d['itemBarcode']
            s = etree.SubElement(z, 'title')
            if 'title' in d and d['title']: s.text = d['title']
            s = etree.SubElement(z, 'author')
            if 'author' in d and d['author']: s.text = d['author']
            s = etree.SubElement(z, 'callNumber')
            if 'callNumber' in d and d['callNumber']:
                s.text = d['callNumber']
            s = etree.SubElement(z, 'patronBarcode')
            if 'patronBarcode' in d and d['patronBarcode']:
                s.text = d['patronBarcode']
            s = etree.SubElement(z, 'patronName')
            if 'patronName' in d and d['patronName']:
                s.text = d['patronName']
            s = etree.SubElement(z, 'requestDate')
            if 'requestDate' in d and d['requestDate']:
                s.text = d['requestDate']
            s = etree.SubElement(z, 'pickupLocation')
            if 'pickupLocation' in d and d['pickupLocation']:
                s.text=d['pickupLocation']
            s = etree.SubElement(z,'requestStatus')
            if 'requestStatus' in d and d['requestStatus']:
                s.text = stat_dict[d['requestStatus']]
            y.append(z)
            count += 1
        x.append(y)
        x = etree.tostring(x, encoding='UTF-8', xml_declaration=True,
                           standalone=True)
        log.info(f"Newly requested items ({count}):\n{x}\n")
    else:
        x = etree.Element('asrResponse')
        etree.SubElement(x, 'code').text = '011'
        etree.SubElement(x, 'message').text = 'Currently no request found'
        x = etree.tostring(x, encoding='UTF-8', xml_declaration=True,
                           standalone=True)
    response = make_response(x, r.status_code)
    response.headers = {'Content-Type': 'application/xml'}
    return response


@app.route('/asrService/asr/updateASRItemStatusAvailable', methods=['post'])
def update_item_status_available():
    m = main_class()
    # Changes item status to 'Available'.
    m.endpoint = '/asrService/asr/updateASRItemStatusAvailable'
    doc = etree.XML(request.get_data())
    d = {e.tag:e.text for e  in doc}
    x = etree.Element('updateASRItem')
    if d:
        etree.SubElement(x, 'itemBarcode').text = d['itemBarcode']
        if 'itemStatus' in d and d['itemStatus']:
            etree.SubElement(x, 'itemStatus').text = d['itemStatus']
        else: etree.SubElement(x, 'itemStatus')
        if 'operatorId' in d and d['operatorId']:
            etree.SubElement(x, 'operatorId').text = d['operatorId']
        else: etree.SubElement(x, 'operatorId')
        doc = etree.tostring(x, encoding='UTF-8',
                             xml_declaration=True,
                             standalone=True,
                             pretty_print=True)
        log.info(f"New item status changes:\n{doc}\n")
    else:
        doc = etree.tostring(x, encoding='UTF-8',
                             xml_declaration=True,
                             standalone=True,
                             pretty_print=True)
    r = requests.post(m.edge['url'] + m.endpoint + m.edge['config'],
                      headers = m.edge['headers'], data = doc,
                      params = m.edge['params'])
    return make_response(r.text, r.status_code)


def check_items_for_null_barcodes(m):
    m.recent_items = m.null_items = []
    m.okapi['params']['accessioned'] = 'false'
    url = f"{m.okapi['url']}/remote-storage/accessions"
    p = m.okapi['params']
    q = {'accessioned': False}
    params = dict(list(p.items()) + list(q.items()))
    r = requests.get(url, headers = m.okapi['headers'],
                     params = m.okapi['params'])
    if not r.ok: raise Exception(f"{r.status_code} {r.reason} {r.text}")
    if r.text:
        doc = json.loads(r.text)
        m.recent_items = doc['accessions']
        m.null_items = [d for d in m.recent_items \
                                if 'itemBarcode' not in d and \
                                'accessionedDateTime' not in d]
    return r


def purge_items_with_null_barcodes(m):
    l = []
    if m.null_items:
        s = '\n\n'.join(['\n'.join([f"{k}: {v}" for k,v in d.items()]) \
                         for d in m.null_items])
        log.info(f"New items w/o barcodes:\n{s}\n")
        m.subject = "Items moved to Mansueto without barcodes"
        m.message = "The following items were moved to Mansueto " \
            "without barcodes. Barcodes are required for remote storage. " \
            "To add barcodes to these items, first move them to a location " \
            "that is not in Mansueto, then assign them barcodes, " \
            "and then move them back to Mansueto again. " \
            "If the items were moved at the holdings " \
            "level, first change the holdings record to a location that " \
            "is not in Mansueto, then add barcodes to the items that " \
            "are missing them, and then change the holdings location " \
            f"back to a Mansueto location again.\n\n{s}"
        send_email(m, m.librarians)
    for d in m.null_items:
        url = f"{m.okapi['url']}/remote-storage/accessions/id/{d['id']}"
        l.append(requests.put(url, headers = m.okapi['headers'],
                              params = m.okapi['params']))
    return l
    

def send_email(m, recipients):
    mailhost =  'smtp.example.com'
    msg = EmailMessage()
    msg['From'] = m.sender
    msg['To'] = recipients
    msg['Subject'] = m.subject
    msg.set_content(m.message)
    server = smtplib.SMTP(mailhost)
    server.send_message(msg)
    server.quit()


# Not working in module, and not needed
@app.route('/asrService/asr/updateASRItemStatusBeingRetrieved',
           methods=['post'])
def update_item_status_being_retrieved():
    m = main_class()
    m.endpoint = '/asrService/asr/updateASRItemStatusBeingRetrieved'
    doc = etree.XML(request.get_data())
    d = {e.tag:e.text for e  in doc}
    return make_response('This API call has not been implemented', 201)


# Not in the API
@app.route('/asrService/asr/updateASRItemStatusMissing', methods=['post'])
def update_item_status_missing():
    m = main_class()
    m.endpoint = '/asrService/asr/updateASRItemStatusMissing'
    doc = etree.XML(request.get_data())
    d = {e.tag:e.text for e  in doc}
    return make_response('This API call has not been implemented', 201)


# No longer in the API
@app.route('/asrService/asr/updateASRRequest', methods=['post'])
def update_request_status():
    s = {'3': 'Item found', '5': 'Item not found'}
    m = main_class()
    m.endpoint = '/asrService/asr/updateASRRequestStatus'
    doc = etree.XML(request.get_data())
    d = {e.tag:e.text for e  in doc}
    return make_response('This API call has not been implemented', 201)

    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
