#!/usr/bin/python
# -*- coding: utf-8 -*-


from holmes.validators.base import Validator


class RobotsValidator(Validator):

    SITEMAP_NOT_FOUND = 'You must specify the location of the Sitemap ' \
                        'using a robots.txt file'

    DISALLOW_NOT_FOUND = 'Disallow directive indicates that robots should ' \
                         'not access the specific directory, subdirectory ' \
                         'or file. '

    DISALLOW_ROOT_PATH = 'Crawlers may not index anything, because ' \
                         'the root path (/) is disallowed.'

    @classmethod
    def get_violation_definitions(cls):
        return {
            'robots.not_found': {
                'title': 'Robots file not found.',
                'description': lambda value: "The robots file at '%s' was not found." % value,
                'category': 'SEO'
            },
            'robots.empty': {
                'title': 'Robots file was empty.',
                'description': lambda value: "The robots file at '%s' was empty." % value,
                'category': 'SEO'
            },
            'robots.sitemap.not_found': {
                'title': 'Sitemap in Robots not found',
                'description': lambda value: cls.SITEMAP_NOT_FOUND,
                'category': 'SEO'
            },
            'robots.disallow.not_found': {
                'title': 'Disallow in Robots not found',
                'description': lambda value: cls.DISALLOW_NOT_FOUND,
                'category': 'SEO'
            },
            'robots.disallow.root_path': {
                'title': 'Disallow: / in Robots',
                'description': lambda value: cls.DISALLOW_ROOT_PATH,
                'category': 'SEO'
            },
        }

    def validate(self):
        if not self.reviewer.is_root():
            return

        response = self.review.data['robots.response']

        if response.status_code > 399:
            self.add_violation(
                key='robots.not_found',
                value=response.url,
                points=100
            )
            return

        if not response.text.strip():
            self.add_violation(
                key='robots.empty',
                value=response.url,
                points=100
            )
            return

        has_sitemap = False

        has_disallow = False
        disallow_root_path = False

        for rawline in response.text.splitlines():
            line = rawline.strip()
            comments = line.find('#')
            if comments >= 0:
                line = line[:comments]
            if line == '' or ':' not in line:
                continue
            key, val = [x.strip() for x in line.split(':', 1)]
            key = key.lower()
            if key == 'sitemap':
                has_sitemap = True
            elif key == 'disallow':
                has_disallow = True
                if val == '/':
                    disallow_root_path = True

        if not has_sitemap:
            self.add_violation(
                key='robots.sitemap.not_found',
                value=None,
                points=100
            )

        if not has_disallow:
            self.add_violation(
                key='robots.disallow.not_found',
                value=None,
                points=100
            )
        elif disallow_root_path:
            self.add_violation(
                key='robots.disallow.root_path',
                value=None,
                points=100
            )
