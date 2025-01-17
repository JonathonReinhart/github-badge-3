import os
import sys
import json
import requests
from pathlib import Path
from pprint import pprint
from datetime import datetime, timedelta
from platform import python_version

from jinja2 import __version__ as jinja2_version
from jinja2 import Environment
from jinja2 import FileSystemLoader

mydir = Path(__file__).resolve().parent

# code from GitHub\github-badge\app\customfilters.py
# ==============================================================

import re
from math import log

# Constants
QUANTAS = ('k', 'M', 'G', 'T', 'P')

def shortnum(value, precision=3):
	value = float(value)
	if value >= 1000:
		order = int(log(value, 1000))
		mult = 10 ** (order * 3)
		num = value / mult
		quanta = QUANTAS[order - 1]
	else:
		num = value
		quanta = ''
	fmt = "%%.%dg%%s" % precision
	return fmt % (num, quanta)


def smarttruncate(value, length=80, suffix='...', pattern=r'\w+'):
	value_length = len(value)
	if value_length > length:
		last_span = (0, value_length)
		for m in re.finditer(pattern, value):
			span = m.span()
			if span[1] > length:
				break
			else:
				last_span = span
		cutoff = last_span[1]
		if  cutoff > length:
			cutoff = length - len(suffix)
		return value[:cutoff] + suffix
	return value


# utility functions
# ==============================================================
def run_query(query, apikey): # A simple function to use requests.post to make the API call. Note the json= section.
	# modified from https://gist.github.com/gbaman/b3137e18c739e0cf98539bf4ec4366ad
	headers = {"Authorization": "Bearer "+apikey}
	request = requests.post('https://api.github.com/graphql', json={'query': query}, headers=headers)
	if request.status_code == 200:
		return request.json()
	else:
		raise Exception("Query failed to run by returning code of {}. {}".format(request.status_code, query))

def file2str(path):
	with open(path, 'r') as file:
		return file.read().strip()

def renderSaveAs(template, out_file, context):
	rendered_html = template.render(context)

	with open(out_file, "w", encoding='utf-8') as fp:
		fp.write(rendered_html)

	print('generated: '+out_file)

def nBound(value,minimum,maximum):
	# return a value within bounds
	return max(min(value,maximum),minimum)

def gen_SparklineSVG(data):
	# generate a 7-day graph 20x14 pixels
	iw, ih = 20, 14

	# get max
	m = 1 # a minimum max of 1
	for day in data:
		m = max(m,day['count'])

	# generate svg
	svg = '<svg viewBox="0 0 {} {}" width="{}" height="{}"><g style="fill:SlateGray">\n'.format(iw,ih,iw,ih)
	for i in range(0,7):
		d = data[i]
		v = round( (d['count'] / m)*ih, 2 ) #scale val
		h = nBound(v,1,ih) #bound val
		x = i*3
		y = ih - h

		svg += '<rect width="2" height="{}" x="{}" y="{}"/>\n'.format(h,x,y)

	svg += '</g></svg>'

	return svg

def GitHubStats(rObj):
	d = rObj['data']
	u = d['user']
	a = u['activity']

	try:
		lr = a['latestRepo'][0]['contributions']['repos'][0]['repository']
	except:
		lr = {}

	# get stargarzers tally and top primary langs
	stargazers = 0
	topLangs = []

	for repo in u['sources']['repos']:
		# process any primary langs
		if (repo['primaryLanguage']) and len(repo['primaryLanguage']):
			lang = repo['primaryLanguage']['name']
			if lang not in topLangs:
				topLangs.append(lang)
		
		# add stargazers to sum
		stars = repo['stargazers']['totalCount']
		stargazers += stars


	# get latest (7 days) contributions / activity
	contribs = []

	for weeks in a['contributionCalendar']['weeks']:
		for days in weeks['contributionDays']:
			contribs.append({
				'count': days['contributionCount'],
				#'date': datetime.fromisoformat(days['date']) # python v3.8+
				'date': days['date']
			})

	# get recent max commits
	max_commits = 0
	for day in contribs:
		max_commits = max(day['count'], max_commits)

	# organize data
	retVal = {
		'login':             u['login'],
		'name':              u['name'],
		'followers':         u['followers']['totalCount'],
		'stargazers':        stargazers,
		'repos':             u['sources']['totalCount'],
		'forks':             d['forks']['repositoryCount'],
		'html_url':          u['url'],
		'avatar_url':        u['avatarUrl'],
		'languages':         topLangs,
		'last_project':      lr.get('name', False),
		'last_project_url':  lr.get('url'),
		'last_project_date': datetime.strptime(lr.get('updatedAt', "1970-01-01T00:00:00Z"), '%Y-%m-%dT%H:%M:%SZ'), # bogus date if last_project is n/a.
		'contribs':          contribs,
		'max_commits':       max_commits
	}

	# set last_project to false if more than 14 days ago, so not recent
	days_elapsed = (datetime.now()-retVal['last_project_date']).days
	if days_elapsed > 14:
		retVal['last_project'] = False

	# print values
	pprint(retVal)

	return retVal


def load_config(path):
	cfgpath = Path(path)
	with open(cfgpath, "r", encoding='utf-8') as fp:
		config = json.load(fp)

	return config


def parse_args():
	import argparse
	ap = argparse.ArgumentParser()
	ap.add_argument('-c', '--config', required=True,
			help="Path to config file")
	ap.add_argument('-o', '--outpath', default="badge.hml",
            help="Output path to generated file")
	return ap.parse_args()

def main():
	args = parse_args()

	# print jinja and python version
	print('Script is running jinja v{} on Python v{}'.format(jinja2_version,python_version()))

	config = load_config(args.config)

	# prep query data
	query = file2str(mydir / 'query.gql') \
		.replace('$USERNAME$', config['username']) \
		.replace('$TIMESTAMP_7DAYSAGO$', (datetime.now() - timedelta(7)).isoformat()) \
		.replace('$TIMESTAMP_YESTERDAY$', (datetime.now() - timedelta(1)).isoformat())

	# get data
	print('running GitHub GraphQL query ...\n')
	result = run_query(query, config['apikey'])

	# process data
	userdata = GitHubStats(result)
	GH_Data = {
		'user': userdata,
		'days': 7,
		'support': True,
		'commit_sparkline': gen_SparklineSVG(userdata['contribs'])
	}

	# setup jinja2
	print('\nrunning jinja2 ...')
	G_j2_env = Environment( loader=FileSystemLoader(mydir) )
	G_j2_env.globals['DATETIME_NOW'] = datetime.now()
	G_j2_env.filters['shortnum'] = shortnum
	G_j2_env.filters['smarttruncate'] = smarttruncate

	# generate / render badge.html
	template = G_j2_env.get_template('badge.j2')
	renderSaveAs(template, args.outpath, GH_Data)

if __name__ == '__main__':
	main()
