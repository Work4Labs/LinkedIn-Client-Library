from lxml import etree
import mappers
import re

class LinkedInXMLParser(object):
    def __init__(self, content):
        self.routing = {
            'network': self.__parse_network_updates,
            'person': self.__parse_personal_profile,
            'job-poster': self.__parse_personal_profile,
            'update-comments': self.__parse_update_comments,
            'connections': self.__parse_connections,
            'error': self.__parse_error,
            'position': self.__parse_position,
            'education': self.__parse_education,
            'people': self.__parse_people_collection
        }
        self.tree = etree.fromstring(content)
        self.root = self.tree.tag
        self.results = self.__forward_tree(self.tree, self.root)
    
    def __forward_tree(self, tree, root):
        results = self.routing[root](tree)
        return results
    
    def __parse_network_updates(self, tree):
        content = LinkedInNetworkUpdateParser(tree).results
        return content
    
    def __parse_personal_profile(self, tree):
        content = LinkedInProfileParser(tree).results
        return content
    
    def __parse_update_comments(self, tree):
        content = LinkedInNetworkCommentParser(tree).results
        return content
    
    def __parse_connections(self, tree):
        content = LinkedInConnectionsParser(tree).results
        return content
    
    def __parse_error(self, tree):
        content = LinkedInErrorParser(tree).results
        return content
    
    def __parse_position(self, tree):
        content = LinkedInPositionParser(tree).results
        return content

    def __parse_education(self, tree):
        content = LinkedInEducationParser(tree).results
        return content
    
    def __parse_people_collection(self, tree):
        ppl = tree.getchildren()
        content = []
        for p in ppl:
            rslts = LinkedInProfileParser(p).results
            content.append(rslts)
        return content
        
class LinkedInNetworkUpdateParser(LinkedInXMLParser):
    def __init__(self, content):
        self.xpath_collection = {
            'first-name': etree.XPath('update-content/person/first-name'),
            'profile-url': etree.XPath('update-content/person/site-standard-profile-request/url'),
            'last-name': etree.XPath('update-content/person/last-name'),
            'timestamp': etree.XPath('timestamp'),
            'updates': etree.XPath('updates'),
            'update': etree.XPath('updates/update'),
            'update-type': etree.XPath('update-type'),
            'update-key': etree.XPath('update-key'),
            #special paths for question/answer updates
            'qa-first-name': etree.XPath('update-content/question/author/first-name'), 
            'qa-last-name': etree.XPath('update-content/question/author/last-name'),   
            'qa-profile-url': etree.XPath('update-content/question/web-url'),
            'jobp-title': etree.XPath('update-content/job/position/title'),
            'jobp-company': etree.XPath('update-content/job/company/name'),
            'jobp-url': etree.XPath('update-content/job/site-job-request/url')
        }
        self.tree = content
        total = self.xpath_collection['updates'](self.tree)[0].attrib['total']
        self.results = self.__build_data(self.tree, total)
    
    def __build_data(self, tree, total):
        results = {}
        objs = []
        results['total'] = total
        updates = self.xpath_collection['update'](tree)
        for u in updates:
            types = self.xpath_collection['update-type'](u)[0].text
            if types == 'QSTN' or types == 'ANSW':
                data = self.__qa_data_builder(u)
            elif types == 'JOBP':
                data = self.__jobp_data_builder(u)
            else:
                data = self.__generic_data_builder(u)
            obj = self.__objectify(data, types, u)
            objs.append(obj)
        results['results'] = objs
        return results
    
    def __generic_data_builder(self, u):
        data = {}
        try:
            data['update_key'] = self.xpath_collection['update-key'](u)[0].text.strip()
        except IndexError:
            pass
        data['first_name'] = self.xpath_collection['first-name'](u)[0].text.strip()
        data['profile_url'] = self.xpath_collection['profile-url'](u)[0].text.strip()
        data['last_name'] = self.xpath_collection['last-name'](u)[0].text.strip()
        data['timestamp'] = self.xpath_collection['timestamp'](u)[0].text.strip()
        return data
        
    def __qa_data_builder(self, u):
        data = {}
        data['first_name'] = self.xpath_collection['qa-first-name'](u)[0].text.strip()
        try:
            data['profile_url'] = self.xpath_collection['qa-profile-url'](u)[0].text.strip()
        except IndexError: #the answers url is in a different spot, that's handled by the object
            pass
        data['last_name'] = self.xpath_collection['qa-last-name'](u)[0].text.strip()
        data['timestamp'] = self.xpath_collection['timestamp'](u)[0].text.strip()
        return data
    
    def __jobp_data_builder(self, u):
        data = {}
        data['job_title'] = self.xpath_collection['jobp-title'](u)[0].text.strip()
        data['job_company'] = self.xpath_collection['jobp-company'](u)[0].text.strip()
        data['profile_url'] = self.xpath_collection['jobp-url'](u)[0].text.strip()
        return data
    
    def __objectify(self, data, u_type, u):
        if u_type == 'STAT':
            obj = mappers.NetworkStatusUpdate(data, u)
        elif u_type == 'CONN':
            obj = mappers.NetworkConnectionUpdate(data, u)
        elif u_type == 'JGRP':
            obj = mappers.NetworkGroupUpdate(data, u)
        elif u_type == 'NCON':
            obj = mappers.NetworkNewConnectionUpdate(data, u)
        elif u_type == 'CCEM':
            obj = mappers.NetworkAddressBookUpdate(data, u)
        elif u_type == 'QSTN':
            obj = mappers.NetworkQuestionUpdate(data, u)
        elif u_type == 'ANSW':
            obj = mappers.NetworkAnswerUpdate(data, u)
        elif u_type == 'JOBP':
            obj = mappers.NetworkJobPostingUpdate(data, u)
        return obj
    
class LinkedInProfileParser(LinkedInXMLParser):
    def __init__(self, content):
        self.tree = content
        self.results = self.__build_data(self.tree)
    
    def __build_data(self, tree):
        results = []
        for p in tree.xpath('/person'):
            person = {}
            for item in p.getchildren():
                if item.tag == 'location':
                    person['location'] = item.getchildren()[0].text
                else:
                    person[re.sub(r'-', '_', item.tag)] = item.text
            obj = mappers.Profile(person, p)
            results.append(obj)
        if not results:
            person = {}
            for item in tree.getchildren():
                person[re.sub(r'-', '_', item.tag)] = item.text
            obj = mappers.Profile(person, tree)
            results.append(obj)
        return results
    
class LinkedInNetworkCommentParser(LinkedInXMLParser):
    def __init__(self, content):
        self.tree = content
        self.comment_xpath = etree.XPath('update-comment')
        self.results = self.__build_data(self.tree)
    
    def __build_data(self, tree):
        if not tree.getchildren():
            return []
        else:
            objs = []
            for c in self.comment_xpath(tree):
                obj = mappers.NetworkUpdateComment(c)
                objs.append(obj)
            return objs
        
class LinkedInConnectionsParser(LinkedInXMLParser):
    def __init__(self, content):
        self.tree = content
        self.total = content.attrib['total']
        self.results = self.__build_data(self.tree)
    
    def __build_data(self, tree):
        results = {}
        results['results'] = []
        for p in tree.getchildren():
            parsed = LinkedInXMLParser(etree.tostring(p)).results[0]
            results['results'].append(parsed)
        results['total'] = self.total
        return results
    
class LinkedInErrorParser(LinkedInXMLParser):
    def __init__(self, content):
        self.tree = content
        self.xpath_collection = {
            'status': etree.XPath('status'),
            'timestamp': etree.XPath('timestamp'),
            'error-code': etree.XPath('error-code'),
            'message': etree.XPath('message')
        }
        self.results = self.__build_data(self.tree)
    
    def __build_data(self, tree):
        data = {}
        data['status'] = self.xpath_collection['status'](tree)[0].text.strip()
        data['timestamp'] = self.xpath_collection['timestamp'](tree)[0].text.strip()
        data['error_code'] = self.xpath_collection['error-code'](tree)[0].text.strip()
        data['message'] = self.xpath_collection['message'](tree)[0].text.strip()
        results = mappers.LinkedInError(data, tree)
        return results
    
class LinkedInPositionParser(LinkedInXMLParser):
    def __init__(self, content):
        self.tree = content
        self.xpath_collection = {
            'id': etree.XPath('id'),
            'title': etree.XPath('title'),
            'summary': etree.XPath('summary'),
            'start-date': etree.XPath('start-date'),
            'end-date': etree.XPath('end-date'),
            'is-current': etree.XPath('is-current'),
            'company': etree.XPath('company/name')
        }
        self.results = self.__build_data(self.tree)
    
    def __build_data(self, tree):
        data = {}
        try:
            data['id'] = self.xpath_collection['id'](tree)[0].text.strip() \
                if len(self.xpath_collection['id'](tree)) else None
        except:
            data['id'] = None
        try:
            data['title'] = self.xpath_collection['title'](tree)[0].text.strip() \
                if len(self.xpath_collection['title'](tree)) else None
        except:
            data['title'] = None
        try:
            data['summary'] = self.xpath_collection['summary'](tree)[0].text.strip() \
                if len(self.xpath_collection['summary'](tree)) else None
        except:
            data['summary'] = None
        try:
            data['start_date'] = self.xpath_collection['start-date'](tree)[0].text.strip() \
                if len(self.xpath_collection['start-date'](tree)) else None
        except:
            data['start_date'] = None
        try:
            data['end_date'] = self.xpath_collection['end-date'](tree)[0].text.strip() \
                if len(self.xpath_collection['end-date'](tree)) else None
        except:
            data['end_date'] = None
        try:
            data['is_current'] = self.xpath_collection['is-current'](tree)[0].text.strip() \
                if len(self.xpath_collection['is-current'](tree)) else None
        except:
            data['is_current'] = None
        try:
            data['company'] = self.xpath_collection['company'](tree)[0].text.strip() \
                if len(self.xpath_collection['company'](tree)) else None
        except:
            data['company'] = None
        results = mappers.Position(data, tree)
        return results

class LinkedInEducationParser(LinkedInXMLParser):
    def __init__(self, content):
        self.tree = content
        self.xpath_collection = {
            'id': etree.XPath('id'),
            'school-name': etree.XPath('school-name'),
            'field-of-study': etree.XPath('field-of-study'),
            'start-date': etree.XPath('start-date/year'),
            'end-date': etree.XPath('end-date/year'),
            'degree': etree.XPath('degree'),
            'activities': etree.XPath('activities')
        }
        self.results = self.__build_data(self.tree)
    
    def __build_data(self, tree):
        data = {}
        try:
            data['id'] = self.xpath_collection['id'](tree)[0].text.strip() \
                        if len(self.xpath_collection['id'](tree)) else None
        except Exception, e:
            print e
            data['id'] = None
        try:
            data['school_name'] = self.xpath_collection['school-name'](tree)[0].text.strip() \
                        if len(self.xpath_collection['id'](tree)) else None
        except Exception, e:
            print e
            data['school_name'] = None
        try:
            data['field_of_study'] = self.xpath_collection['field-of-study'](tree)[0].text.strip() \
                        if len(self.xpath_collection['id'](tree)) else None
        except:
            data['field_of_study'] = None
        try:
            data['start_date'] = self.xpath_collection['start-date'](tree)[0].text.strip() \
                        if len(self.xpath_collection['id'](tree)) else None
        except:
            data['start_date'] = None
        try:
            data['end_date'] = self.xpath_collection['end-date'](tree)[0].text.strip() \
                        if len(self.xpath_collection['id'](tree)) else None
        except:
            data['end_date'] = None
        try:
            data['degree'] = self.xpath_collection['degree'](tree)[0].text.strip() \
                        if len(self.xpath_collection['id'](tree)) else None
        except:
            data['degree'] = None
        try:
            data['activities'] = self.xpath_collection['activities'](tree)[0].text.strip() \
                        if len(self.xpath_collection['id'](tree)) else None
        except:
            data['activities'] = None
        results = mappers.Education(data, tree)
        return results