#!/usr/bin/python
# -*- coding: utf-8 -*-

from uuid import uuid4

from motorengine import Document, URLField, StringField, ReferenceField, DateTimeField, UUIDField


class Page(Document):
    uuid = UUIDField(default=uuid4)
    title = StringField()
    url = URLField(required=True)
    added_date = DateTimeField(required=True, auto_now_on_insert=True)
    updated_date = DateTimeField(required=True, auto_now_on_insert=True, auto_now_on_update=True)

    domain = ReferenceField("holmes.models.domain.Domain", required=True)
    last_review = ReferenceField("holmes.models.review.Review", required=False)
