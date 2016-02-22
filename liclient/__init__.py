#! usr/bin/env python

import datetime
import re
import time
import urllib
import urlparse
import oauth2 as oauth

from httplib2 import HttpLib2ErrorWithResponse
import json

from parsers.lixml import LinkedInXMLParser
from lxml import etree
from lxml.builder import ElementMaker


class LinkedInAPI(object):
    def __init__(self, ck, cs):
        self.consumer_key = ck
        self.consumer_secret = cs

        self.api_profile_url = 'http://api.linkedin.com/v1/people/~'
        self.api_profile_connections_url = 'http://api.linkedin.com/v1/people/~/connections'
        self.api_network_update_url = 'http://api.linkedin.com/v1/people/~/network'
        self.api_comment_feed_url = 'http://api.linkedin.com/v1/people/~/network/updates/' + \
            'key={NETWORK UPDATE KEY}/update-comments'
        self.api_update_status_url = 'http://api.linkedin.com/v1/people/~/current-status'
        self.api_share = 'http://api.linkedin.com/v1/people/~/shares'
        self.api_mailbox_url = 'http://api.linkedin.com/v1/people/~/mailbox'

        self.base_url = 'https://api.linkedin.com'
        self.li_url = 'http://www.linkedin.com'

        self.request_token_path = '/uas/oauth/requestToken'
        self.access_token_path = '/uas/oauth/accessToken'
        self.authorize_path = '/uas/oauth/authorize'

        self.consumer = oauth.Consumer(self.consumer_key, self.consumer_secret)

        self.valid_network_update_codes = ['ANSW', 'APPS', 'CONN', 'JOBS',
                                           'JGRP', 'PICT', 'RECU', 'PRFU',
                                           'QSTN', 'STAT']

    def get_request_token(self, redirect_url=None):
        """
        Get a request token based on the consumer key and secret to supply the
        user with the authorization URL they can use to give the application
        access to their LinkedIn accounts
        """
        client = oauth.Client(self.consumer)
        request_token_url = self.base_url + self.request_token_path

        additional_param = {}
        if redirect_url:
            additional_param = {
                'body':    "oauth_callback=%s" % urllib.quote_plus(redirect_url),
                'headers': {'Content-Type': 'application/x-www-form-urlencoded'}
            }

        resp, content = client.request(request_token_url, 'POST', **additional_param)

        request_token = dict(urlparse.parse_qsl(content))
        return request_token

    def get_access_token(self, request_token, verifier):
        """
        Get an access token based on the generated request_token and the
        oauth verifier supplied in the return URL when a user authorizes their
        application
        """
        token = oauth.Token(
            request_token['oauth_token'],
            request_token['oauth_token_secret']
        )
        token.set_verifier(verifier)
        client = oauth.Client(self.consumer, token)
        access_token_url = self.base_url + self.access_token_path

        resp, content = client.request(access_token_url, 'POST')
        access_token = dict(urlparse.parse_qsl(content))
        return access_token

    def get_user_profile(self, access_token, selectors=None, **kwargs):
        """
        Get a user profile.  If keyword argument "id" is not supplied, this
        returns the current user's profile, else it will return the profile of
        the user whose id is specificed.  The "selectors" keyword argument takes
        a list of LinkedIn compatible field selectors.
        """

        # Now using json api - GL
        kwargs['format'] = 'json'
        url = self.api_profile_url

        assert isinstance(selectors, (tuple, list)), '"Keyword argument "selectors" must be of type "list" or "tuple"'
        if selectors:
            url = self.prepare_field_selectors(selectors, url)

        user_token, url = self.prepare_request(access_token, url, kwargs)
        client = oauth.Client(self.consumer, user_token)
        resp, content = client.request(url, 'GET')

        if resp.status >= 500:
            raise HttpLib2ErrorWithResponse(resp.reason, resp, content)
        return resp, json.loads(content)

    def get_user_connections(self, access_token, selectors=None, **kwargs):
        """
        Get the connections of the current user.  Valid keyword arguments are
        "count" and "start" for the number of profiles you wish returned.  Types
        are automatically converted from integer to string for URL formatting
        if necessary.
        """

        # Now using json api - GL
        kwargs['format'] = 'json'

        if selectors:
            url = self.prepare_field_selectors(selectors, self.api_profile_connections_url)

        user_token, url = self.prepare_request(access_token, url, kwargs)
        client = oauth.Client(self.consumer, user_token)
        resp, content = client.request(url, 'GET')

        if resp.status >= 500:
            raise HttpLib2ErrorWithResponse(resp.reason, resp, content)
        return resp, json.loads(content)

    def get_network_updates(self, access_token, **kwargs):
        """Get network updates for the current user.  Valid keyword arguments are
        "count", "start", "type", "before", and "after".  "Count" and "start" are for the number
        of updates to be returned.  "Type" specifies what type of update you are querying.
        "Before" and "after" set the time interval for the query.  Valid argument types are
        an integer representing UTC with millisecond precision or a Python datetime object.
        """
        if 'type' in kwargs.keys():
            assert isinstance(kwargs['type'], (tuple, list)), 'Keyword argument "type" must be of type "list"'
            [self.check_network_code(c) for c in kwargs['type']]

        if 'before' in kwargs.keys():
            kwargs['before'] = self.dt_obj_to_string(kwargs['before']) if kwargs.get('before') else None
        if 'after' in kwargs.keys():
            kwargs['after'] = self.dt_obj_to_string(kwargs['after']) if kwargs.get('after') else None

        user_token, url = self.prepare_request(access_token, self.api_network_update_url, kwargs)
        client = oauth.Client(self.consumer, user_token)
        resp, content = client.request(url, 'GET')
        content = self.clean_dates(content)
        return LinkedInXMLParser(content).results

    def get_comment_feed(self, access_token, network_key):
        """
        Get a comment feed for a particular network update.  Requires the update key
        for the network update as returned by the API.
        """
        url = re.sub(r'\{NETWORK UPDATE KEY\}', network_key, self.api_comment_feed_url)
        user_token, url = self.prepare_request(access_token, url)
        client = oauth.Client(self.consumer, user_token)
        resp, content = client.request(url, 'GET')
        content = self.clean_dates(content)
        return LinkedInXMLParser(content).results

    def submit_comment(self, access_token, network_key, bd):
        """
        Submit a comment to a network update.  Requires the update key for the network
        update that you will be commenting on.  The comment body is the last positional
        argument.  NOTE: The XML will be applied to the comment for you.
        """
        bd_pre_wrapper = '<?xml version="1.0" encoding="UTF-8"?><update-comment><comment>'
        bd_post_wrapper = '</comment></update-comment>'
        xml_request = bd_pre_wrapper + bd + bd_post_wrapper
        url = re.sub(r'\{NETWORK UPDATE KEY\}', network_key, self.api_comment_feed_url)
        user_token, url = self.prepare_request(access_token, url)
        client = oauth.Client(self.consumer, user_token)
        return client.request(url, method='POST', body=xml_request, headers={'Content-Type': 'application/xml'})

    def set_status_update(self, access_token, bd):
        """
        Set the status for the current user.  The status update body is the last
        positional argument.  NOTE: The XML will be applied to the status update
        for you.

        WARNING: the status to set should be utf-8 encoded before passing it to that function
        """
        bd_pre_wrapper = '<?xml version="1.0" encoding="UTF-8"?><current-status>'
        bd_post_wrapper = '</current-status>'
        xml_request = bd_pre_wrapper + bd + bd_post_wrapper
        user_token, url = self.prepare_request(access_token, self.api_update_status_url)
        client = oauth.Client(self.consumer, user_token)
        return client.request(url, method='PUT', body=xml_request)

    def share(self, access_token, share_content):
        '''
        WARNING: all the parameter of the share content to set should be utf-8
        encoded before passing it to that function
        '''
        user_token, url = self.prepare_request(access_token, self.api_share)
        client = oauth.Client(self.consumer, user_token)
        resp, content = client.request(
            url,
            method='POST',
            body=json.dumps(share_content),
            headers={
                'x-li-format': 'json',
                'Content-Type': 'application/json'
            }
        )

        if resp.status >= 500:
            raise HttpLib2ErrorWithResponse(resp.reason, resp, content)
        return resp, json.loads(content)

    def search(self, access_token, data, field_selector_string=None):
        """
        Use the LinkedIn Search API to find users.  The criteria for your search
        should be passed as the 2nd positional argument as a dictionary of key-
        value pairs corresponding to the paramters allowed by the API.  Formatting
        of arguments will be done for you (i.e. lists of keywords will be joined
        with "+")
        """
        srch = LinkedInSearchAPI(data, access_token, field_selector_string)
        client = oauth.Client(self.consumer, srch.user_token)
        rest, content = client.request(srch.generated_url, method='GET')
        # print content # useful for debugging...
        return LinkedInXMLParser(content).results

    def send_message(self, access_token, recipients, subject, body):
        """
        Send a message to a connection.  "Recipients" is a list of ID numbers,
        "subject" is the message subject, and "body" is the body of the message.
        The LinkedIn API does not allow HTML in messages.  All XML will be applied
        for you.
        """
        assert isinstance(recipients, (tuple, list)), '"Recipients argument" (2nd position) must be of type "list"'
        mxml = self.message_factory(recipients, subject, body)
        user_token, url = self.prepare_request(access_token, self.api_mailbox_url)
        client = oauth.Client(self.consumer, user_token)
        return client.request(url, method='POST', body=mxml, headers={'Content-Type': 'application/xml'})

    def send_invitation(self, access_token, recipients, subject, body, **kwargs):
        """
        Send an invitation to a user.  "Recipients" is an ID number OR email address
        (see below), "subject" is the message subject, and "body" is the body of the message.
        The LinkedIn API does not allow HTML in messages.  All XML will be applied
        for you.

        NOTE:
        If you pass an email address as the recipient, you MUST include "first_name" AND
        "last_name" as keyword arguments.  Conversely, if you pass a member ID as the
        recipient, you MUST include "name" and "value" as keyword arguments.  Documentation
        for obtaining those values can be found on the LinkedIn website.
        """
        if 'first_name' in kwargs.keys():
            mxml = self.invitation_factory(recipients, subject, body,
                                        first_name=kwargs['first_name'], last_name=kwargs['last_name'])
        else:
            mxml = self.invitation_factory(recipients, subject, body,
                                        name=kwargs['name'], value=kwargs['value'])
        user_token, url = self.prepare_request(access_token, self.api_mailbox_url)
        client = oauth.Client(self.consumer, user_token)
        return client.request(url, method='POST', body=mxml, headers={'Content-Type': 'application/xml'})

    def prepare_request(self, access_token, url, kws={}):
        user_token = oauth.Token(access_token['oauth_token'],
                        access_token['oauth_token_secret'])
        prep_url = url
        if kws and 'id' in kws.keys():
            prep_url = self.append_id_args(kws['id'], prep_url)
            del kws['id']
        for k in kws:
            if kws[k]:
                if '?' not in prep_url:
                    prep_url = self.append_initial_arg(k, kws[k], prep_url)
                else:
                    prep_url = self.append_sequential_arg(k, kws[k], prep_url)
        prep_url = re.sub('&&', '&', prep_url)
        return user_token, prep_url

    def append_id_args(self, ids, prep_url):
        assert isinstance(ids, (tuple, list)), 'Keyword argument "id" must be a list'
        if len(ids) > 1:
            prep_url = re.sub('/~', '::(', prep_url)  # sub out the ~ if a user wants someone else's profile
            for i in ids:
                prep_url += 'id=' + i + ','
            prep_url = re.sub(',$', ')', prep_url)
        else:
            prep_url = re.sub('~', 'id=' + ids[0], prep_url)
        return prep_url

    def append_initial_arg(self, key, args, prep_url):
        assert '?' not in prep_url, 'Initial argument has already been applied to %s' % prep_url
        if isinstance(args, (tuple, list)):
            prep_url += '?' + key + '=' + str(args[0])
            if len(args) > 1:
                prep_url += ''.join(['&' + key + '=' + str(arg) for arg in args[1:]])
        else:
            prep_url += '?' + key + '=' + str(args)
        return prep_url

    def append_sequential_arg(self, key, args, prep_url):
        if isinstance(args, (tuple, list)):
            prep_url += '&' + ''.join(['&' + key + '=' + str(arg) for arg in args])
        else:
            prep_url += '&' + key + '=' + str(args)
        return prep_url

    def prepare_field_selectors(self, selectors, url):
        prep_url = url
        selector_string = ':('
        selector_string += ','.join(selectors)
        selector_string += ')'
        prep_url += selector_string
        return prep_url

    def check_network_code(self, code):
        if code not in self.valid_network_update_codes:
            raise ValueError('Code %s not a valid update code' % code)

    def clean_dates(self, content):
        data = etree.fromstring(content)
        for d in data.iter(tag=etree.Element):
            try:
                trial = int(d.text)
                if len(d.text) > 8:
                    dt = datetime.datetime.fromtimestamp(float(trial) / 1000)
                    d.text = dt.strftime('%m/%d/%Y %I:%M:%S')
            except:
                continue
        return etree.tostring(data)

    def dt_obj_to_string(self, dtobj):
        if isinstance(dtobj, (int, str, long)):
            return dtobj
        elif hasattr(dtobj, 'timetuple'):
            return time.mktime(int(dtobj.timetuple()) * 1000)
        else:
            raise TypeError('Inappropriate argument type - use either a datetime object, \
                            string, or integer for timestamps')

    def message_factory(self, recipients, subject, body):
        rec_path = '/people/'

        E = ElementMaker()
        MAILBOX_ITEM = E.mailbox_item
        RECIPIENTS = E.recipients
        RECIPIENT = E.recipient
        PERSON = E.person
        SUBJECT = E.subject
        BODY = E.body

        recs = [RECIPIENT(PERSON(path=rec_path + r)) for r in recipients]

        mxml = MAILBOX_ITEM(
            RECIPIENTS(
                *recs
            ),
            SUBJECT(subject),
            BODY(body)
        )
        return re.sub('mailbox_item', 'mailbox-item', etree.tostring(mxml))

    def invitation_factory(self, recipient, subject, body, **kwargs):
        id_rec_path = '/people/id='
        email_rec_path = '/people/email='

        E = ElementMaker()
        MAILBOX_ITEM = E.mailbox_item
        RECIPIENTS = E.recipients
        RECIPIENT = E.recipient
        PERSON = E.person
        SUBJECT = E.subject
        BODY = E.body
        CONTENT = E.item_content
        REQUEST = E.invitation_request
        CONNECT = E.connect_type
        FIRST = E.first_name
        LAST = E.last_name
        AUTH = E.authorization
        NAME = E.name
        VALUE = E.value

        if not '@' in recipient:
            recs = RECIPIENT(PERSON(path=id_rec_path + recipient))
            auth = CONTENT(REQUEST(CONNECT('friend'), AUTH(NAME(kwargs['name']), VALUE(kwargs['value']))))
        else:
            recs = RECIPIENT(
                        PERSON(
                            FIRST(kwargs['first_name']),
                            LAST(kwargs['last_name']),
                            path=email_rec_path + recipient
                        )
                    )
            auth = CONTENT(REQUEST(CONNECT('friend')))
        mxml = MAILBOX_ITEM(
            RECIPIENTS(
                *recs
            ),
            SUBJECT(subject),
            BODY(body),
            auth
        )
        return re.sub('_', '-', etree.tostring(mxml))


class LinkedInSearchAPI(LinkedInAPI):

    def __init__(self, params, access_token, field_selector_string=None):
        self.api_search_url = 'http://api.linkedin.com/v1/people-search'
        if field_selector_string:
            self.api_search_url += ':' + field_selector_string
        self.routing = {
            'keywords': self.keywords,
            'name': self.name,
            'current_company': self.current_company,
            'current_title': self.current_title,
            'location_type': self.location_type,
            'network': self.network,
            'sort_criteria': self.sort_criteria
        }
        self.user_token, self.generated_url = self.do_process(access_token, params)

    def do_process(self, access_token, params):
        assert type(params) == type(dict()), 'The passed parameters to the Search API must be a dictionary.'
        user_token = oauth.Token(
            access_token['oauth_token'],
            access_token['oauth_token_secret']
        )
        url = self.api_search_url
        for p in params:
            if self.routing.get(p):
                self.routing.get(p)(url, params[p])
                del params[p]
        url = self.process_remaining_params(url, params)
        return user_token, url

    def process_remaining_params(self, prep_url, ps):
        for p in ps:
            prep_url = self.append_arg(p, ps[p], prep_url)
        return prep_url

    def keywords(self, url, ps):
        return self.list_argument(url, ps, 'keywords')

    def name(self, url, ps):
        return self.list_argument(url, ps, 'name')

    def current_company(self, url, ps):
        return self.true_false_argument(url, ps, 'current-company')

    def current_title(self, url, ps):
        return self.true_false_argument(url, ps, 'current-title')

    def location_type(self, prep_url, ps):
        assert ps in ('I', 'Y'), 'Valid parameter types for search-location-type are "I" and "Y"'
        self.append_arg('search-location-type', ps, prep_url)

    def network(self, prep_url, ps):
        assert ps in ('in', 'out'), 'Valid parameter types for network are "in" and "out"'
        return self.append_arg('network', ps, prep_url)

    def sort_criteria(self, prep_url, ps):
        assert ps in ('recommenders', 'distance', 'relevance'), 'Valid parameter types for sort-criteria \
                            are "recommenders", "distance", and "relevance"'
        return self.append_arg('sort-criteria', ps, prep_url)

    def true_false_argument(self, prep_url, ps, arg):
        ps = 'true' if ps else 'false'
        return self.append_arg(arg, ps, prep_url)

    def list_argument(self, prep_url, ps, arg):
        li = '+'.join(ps)
        return self.append_arg(arg, li, prep_url)

    def append_arg(self, key, arg, prep_url):
        try:
            prep_url = self.append_initial_arg(key, arg, prep_url)
        except AssertionError:
            prep_url = self.append_sequential_arg(key, arg, prep_url)
        return prep_url
