from urllib2 import urlopen, URLError
from urllib import urlencode, quote
from xml.etree import cElementTree as etree

from flask import url_for, request, redirect, flash, abort, session

from buddyup.app import app
from buddyup.database import User, Visit, db
from buddyup.util import args_get

VALIDATE_URL = "{server}/serviceValidate?{args}"
CAS_NS = 'http://www.yale.edu/tp/cas'
TAG_SUCCESS = './/{%s}authenticationSuccess' % CAS_NS
TAG_FAILURE = './/{%s}authenticationFailure' % CAS_NS
TAG_USER = './/{%s}user' % CAS_NS


@app.before_first_request
def setup_cas():
    # Cache various URL's
    app.cas_server = app.config['CAS_SERVER']
    app.cas_service = url_for('login', _external=True)
    app.logger.info("Setting CAS service to %s", app.cas_service)
    app.cas_login = "{server}/login?service={service}".format(
        server=app.cas_server,
        service=quote(app.cas_service))
    app.logger.info("Setting CAS log URL to %s", app.cas_login)
    app.cas_logout = "{server}/logout?url={root}".format(
        server=app.cas_server,
        root=url_for('index', _external=True))


@app.route('/login')
def login():
    if 'ticket' in request.args:
        status, message = validate(args_get('ticket'))
        if status == 0:
            user_name = message
            user_record = User.query.filter(User.user_name == user_name).first()
            # No user with that user name
            if user_record is None:
                new_user_record = User(user_name=user_name)
                db.session.add(new_user_record)
                db.session.commit()
                user_id = new_user_record.id
                url = url_for('welcome')
            else:
                url = url_for('home')
                user_id = user_record.id
            session['user_id'] = user_id

            visit_record = Visit(user_id=user_id)
            db.session.add(visit_record)
            db.session.commit()

            return redirect(url)
        else:
            app.logger.error(message)
            abort(status)
    else:
        return redirect(app.cas_login)


@app.route('/logout')
def logout():
    # TODO: Some indication of success?
    session.clear()
    return redirect(app.cas_logout)


def validate(ticket):
    """
    Validate the given ticket against app.config['CAS_HOST'] and set
    session variables.
    
    
    Returns (status, message)
    
    status: Desired HTTP status. 0 on success
    message: Message on failure, None on success
    """

    cas_server = app.cas_server
    service = app.cas_service
    args = {
        'service': service,
        'ticket': ticket
    }
    url = VALIDATE_URL.format(server=cas_server,
                              args=urlencode(args))
    app.logger.info("Validating at URL " + url)
    try:
        req = urlopen(url)
        tree = etree.parse(req)
    except URLError as e:
        return 500, "Error contacting CAS server: {}".format(e)
    except etree.ParseError:
        return 500, "Bad response from CAS server: ParseError"

    failure_elem = tree.find(TAG_FAILURE)
    if failure_elem is not None:
        return 500, "Failure: " + failure_elem.text.strip()

    success_elem = tree.find(TAG_SUCCESS)
    if success_elem is not None:
        user_name = success_elem.find(TAG_USER).text.strip()
        return 0, user_name
    else:
        app.logger.error('bad response: %s', etree.tostring(tree.getroot()))
        return 500, "Bad response from CAS server: no success/failure"
