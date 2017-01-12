## osp-utils

Collection of OpenStack-related commands that would be too
annoying or complex to do in a shell script.

Can also be used as a container:

```
# atomic run jlebon/osp-utils upload http://example.com/img.qcow2.gz
```

## Commands

### upload

Upload an image to the Glance image service. Gzipped images
are supported. Optionally give it a name, make it unique,
and share it with other tenants.

```
usage: main.py upload [-h] [--name NAME] [--unique] [--image-id-file FILE]
                      [--share-with TENANT_ID]
                      url

positional arguments:
  url                   URL of image to upload

optional arguments:
  -h, --help            show this help message and exit
  --name NAME           name for the image
  --unique              delete all other images of the same name
  --image-id-file FILE  write image ID to a file
  --share-with TENANT_ID
                        ID of tenant to share with (this option can be
                        repeated)
```

### rename

Rename an image. Optionally make it unique.

```
usage: main.py rename [-h] [--unique] image_id name

positional arguments:
  image_id    ID of the image to rename
  name        name to which to rename

optional arguments:
  -h, --help  show this help message and exit
  --unique    delete all other images of the same name
```
