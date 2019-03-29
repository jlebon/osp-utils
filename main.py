#!/usr/bin/env python3

"""
    A collection of wrapper commands around the OpenStack Python API.
"""

import os
import sys
import bz2
import gzip
import lzma
import argparse
import requests
import subprocess

from keystoneauth1.identity import v3
from keystoneauth1 import session
from glanceclient import Client

# XXX: hidden API abuse alert
from glanceclient.common import progressbar


def main():
    "Main entry point."

    args = parse_args()
    args.func(args)


def parse_args():

    parser = argparse.ArgumentParser()
    parser.add_argument('--auth-url', default=os.environ.get('OS_AUTH_URL'))
    parser.add_argument('--project-id', default=os.environ.get('OS_PROJECT_ID'))
    parser.add_argument('--project-domain-id',
                        default=os.environ.get('OS_PROJECT_DOMAIN_ID'))
    parser.add_argument('--username', default=os.environ.get('OS_USERNAME'))
    parser.add_argument('--password', default=os.environ.get('OS_PASSWORD'))
    subparsers = parser.add_subparsers(dest='cmd', title='subcommands')
    subparsers.required = True

    upload = subparsers.add_parser('upload', help='upload an image')
    upload.add_argument('url', help='URL of image to upload')
    upload.add_argument('--name', help='name for the image')
    upload.add_argument('--unique', action='store_true',
                        help='delete all other images of the same name')
    upload.add_argument('--image-id-file', metavar='FILE',
                        help='write image ID to a file')
    upload.add_argument('--share-with', action='append', metavar='TENANT_ID',
                        default=[], help='ID of tenant to share with (this '
                        'option can be repeated)')
    upload.set_defaults(func=cmd_upload)

    rename = subparsers.add_parser('rename', help='rename an image')
    rename.add_argument('image_id', help='ID of the image to rename')
    rename.add_argument('name', help='name to which to rename')
    rename.add_argument('--unique', action='store_true',
                        help='delete all other images of the same name')
    rename.set_defaults(func=cmd_rename)

    rename = subparsers.add_parser('glance', help='call glance directly')
    rename.add_argument('args', nargs=argparse.REMAINDER, default=[],
                        help="pass these arguments")
    rename.set_defaults(func=cmd_glance)

    return parser.parse_args()


def cmd_upload(args):

    print("INFO: authenticating")
    glance = glance_session_from_args(args)

    print("INFO: creating image")
    new_img = glance.images.create(disk_format='qcow2',
                                   container_format='bare',
                                   hw_rng_model='virtio') # RHBZ#1572944
    print("INFO: new image ID is", new_img.id)

    try:
        print("INFO: uploading image")
        upload_image_from_url(glance, new_img.id, args.url)

        # remove self from the list of tenants with which to share
        if args.tenant_id in args.share_with:
            args.share_with.remove(args.tenant_id)

        if len(args.share_with) > 0:
            print("INFO: sharing with tenants")
            for tenant in args.share_with:
                glance.image_members.create(new_img.id, tenant)

            # We actually don't *have* to do the below. The image is
            # already accessible in the tenants, though they won't
            # show up in a full listing until accepted. So let's try
            # to be nice.

            # We only support sharing with tenants under the same
            # username/password.

            # XXX: Consider making this part optional since it assumes
            # we have access to the other tenants.
            accept_image_in_tenants(new_img.id, args.share_with,
                                    args.project_domain_id, args.auth_url,
                                    args.username, args.password)

        if args.name:
            # The Python API is not fully compatible with v2 yet,
            # e.g. update() is spotty, so let's use v1.
            glance1 = glance_session_from_args(args, 1)
            print("INFO: renaming to", args.name)
            glance1.images.update(new_img.id, name=args.name)

        if args.image_id_file:
            print("INFO: write image id to file", args.image_id_file)
            with open(args.image_id_file, 'w') as f:
                f.write(new_img.id)

    except Exception as e:
        print("INFO: deleting new image")
        glance.images.delete(new_img.id)
        raise e

    if args.unique:
        print("INFO: deleting other images of the same name")
        make_image_unique_by_name(glance, new_img.id, args.name)


def cmd_rename(args):

    print("INFO: authenticating")
    glance = glance_session_from_args(args)

    # The Python API is not fully compatible with v2 yet,
    # e.g. update() is spotty, so let's use v1.
    glance1 = glance_session_from_args(args, 1)
    print("INFO: renaming to", args.name)
    glance1.images.update(args.image_id, name=args.name)

    if args.unique:
        print("INFO: deleting other images of the same name")
        make_image_unique_by_name(glance, args.image_id, args.name)


def glance_session(auth_url, project_id, project_domain_id, username, password, version=2):
    auth = v3.Password(auth_url=auth_url,
                       project_id=project_id,
                       username=username,
                       password=password,
                       project_domain_id=project_domain_id,
                       user_domain_name='redhat.com')
    mysession = session.Session(auth=auth)

    # the Python API is not fully compatible with v2 yet,
    # e.g. update() is spotty
    return Client(version, session=mysession)


def glance_session_from_args(args, version=2):
    return glance_session(args.auth_url, args.project_id,
                          args.project_domain_id,
                          args.username, args.password, version)


def find_images_by_name(glance, name):
    found_imgs = []
    for img in glance.images.list():
        if img.name == name:
            found_imgs.append(img)
    return found_imgs


def upload_image_from_url(glance, img, image_url):

    resp = requests.get(image_url, stream=True)
    if resp.status_code != requests.codes.ok:  # pylint: disable=no-member
        raise Exception("Received HTTP %d" % resp.status_code)

    f_in = resp.raw
    if 'Content-Length' in resp.headers:
        f_in = progressbar.VerboseFileWrapper(f_in,
                                              resp.headers['Content-Length'])

    if image_url.endswith('.gz'):
        f_in = gzip.GzipFile(fileobj=f_in, mode='rb')
    elif image_url.endswith('.xz'):
        f_in = lzma.open(f_in)
    elif image_url.endswith('.bz2'):
        f_in = bz2.open(f_in)

    glance.images.upload(img, f_in)


def accept_image_in_tenants(img, projects, project_domain_id, auth_url,
                            username, password):
    for project in projects:
        glance = glance_session(auth_url, project, project_domain_id,
                                username, password)
        glance.image_members.update(img, tenant, 'accepted')


def make_image_unique_by_name(glance, img_id, name):
    imgs = find_images_by_name(glance, name)
    imgs = [img for img in imgs if img.id != img_id]
    for img in imgs:
        # NB: This assumes that we're in the same tenant as
        # the one that originally uploaded the image(s).
        # Otherwise, we'd get a 403.
        glance.images.delete(img.id)


def cmd_glance(args):
    subprocess.run(['glance'] + args.args, check=True)


if __name__ == "__main__":
    sys.exit(main())
