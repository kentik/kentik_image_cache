# Kentik Image Cache
Application for caching of images rendered by the _/query/topxchart_ Kentik API method.  
   
The application provides API method allowing to invoke _/query/topxchart_ Kentik API method and returns unique identifiers  
which can be later used to retrieve the corresponding image (or error message).   
  
TLS and eventual user authentication must be handled by external proxy (e.g. [Traefik](https://github.com/tiangolo/blog-posts/blob/master/deploying-fastapi-apps-with-https-powered-by-traefik/README.md))  
  
## API endpoints
| end-point | method | operation | request data | response data |
| :---------| :----- | :---------| :----------- | :------------ |
| /requests  | POST | Initiate query request to Kentik API’s /query/topxchart end-point | **api_query:** [JSON object](https://kb.kentik.com/v0/Ec04.htm#Ec04-Query_API_Request_JSON) (passed to Kentik API without modification), **ttl:** (optional int) desired storage duration in seconds | **On success:** image ID, **On error:** JSON error message |
| /image/{id}  | GET | Retrieve previously requested image | None | **On success:** Image data according to the format specified in the corresponding request, **On error:** Status code and error message returned by Kentik API |
| /info       | GET | Return information about cache content | None | JSON object |
| /favicon.ico | GET | Return favicon | None | image/x-icon |

## Image Identifiers
Unique image identifiers returned by the app are constructed as:  
`sha256(<query_data>).hexdigest_<expiration_time_in_unix_epoch>`  
Example:  
`4295aa38281c869ae8827320d407bf1dd1f38a7bf65af00551ce461e70f863d5\_1620973821.2844`

## Application configuration
The application has following configurable parameters which can be either provided in environment variables (variables names must be all capital letters) or in the `.env` file in the root folder of the app:  
  
  | parameter | required | purpose | default value |
  | :---------| :------: | :------ | :------------ | 
  | KT_AUTH_EMAIL | yes | Authentication to Kentik API | |
  | KT_AUTH_TOKEN | yes | Authentication to Kentik API | |
  | KENTIK_API_URL | no | URL of Kentik API service | https://api.kentik.com/api/v5 |
  | KENTIK_API_RETRIES  | no | Number of retries on transient failures | 3 |
  | KENTIK_API_TIMEOUT | no | Timeout for requests to Kentik API | 60 seconds |
  | DEFAULT_TTL| no | Default cache entry lifetime | 300 seconds |
  | ENTRY_WAIT_TIMEOUT  | no | Timeout for cache entry to become active | retries * timeout + 5 seconds |
  | CACHE_PATH  | yes | Directory for storing cached content | |
  | CACHE_MAINTENANCE_PERIOD  | no | Interval for periodic cache pruning | 60 seconds |

## Basic Operations
### Happy Path
![Normal operation sequence diagram](docs/normal_operations.png)

On POST request to the _/requests_ end-point, the Image Cache performs following actions:
1) generates unique image id
2) attempts to locate entry with the same id in the cache
   ```
   if not found
      create new pending entry storing the request body
      start background task for retrieving the image from Kentik API
   else
      store the image id of the entry
   ```
3) returns the image id to the client

On successful retrieval of the image from Kentik API, Image Cache:
1) stores the image data in the pending entry
2) marks the entry active

On GET request to the _/image/<id>_ end-point, the Image Cache:
1) attempts to locate the entry <id> in the cache
```
  if found
    if expired
      return 404 to the client
    if pending
        return 200 and image data to the client
    wait for entry to become active
    if active
        return 200 and image data to the client
    else
        return 500 error to the client
  else
    return 404 error to the client
```

### Handling of Kentik API Errors
![API error handling sequence diagram](docs/api_error_handling.png)

### Application Restart
The current design assumes that local storage used by the cache is persistent and services application/container restarts.
If this is not true, application restart will obviously cause all cached content to be lost.
On application restart, the Image Cache initializes the local cache before beginning to server requests on the 2 API end-points.
Cache initialization steps:
1) Load data to cache from filesystem
2) Walk all pending entries
   - remove expired entries
   - start retrieval of images from Kentik API (using the query data stored in pending entries) for remaining entries
3) Walk all active entries and remove expired ones

## Requirements
- Python 3.8 or newer
- FastAPI
- kentik-api 0.2.0 (or newer)

## Installation

### Deployment in Docker
The bellow procedure assumes:
- Unix/Linux-like operating system
- functional `git` installation
- Docker executed on the host on which the image is built
- User running the procedure has sufficient permissions, including communication with the docker server

#### Clone repo to local disk:
```shell
git clone https://github.com/kentik/kentik_image_cache.git
```

#### Create docker image
```shell
cd kentik_image_cache
docker build -t kentik_image_cache .
```
#### Create cache directory (to be mounted in the container)
The directory should be located on filesystem with enough of disk space and must be readable and writeable
to the user with whose identity Docker containers are executed.
```shell
mkdir -p /opt/kentik_image_cache
chown root:docker /opt/kentik_image_cache
```

#### Start the docker container
The bellow procedure passes Kentik authentication to the container via environment variables.
- _<kentik_user_mail>_ has to be replaced with the e-mail registered with the Kentik user
- _<kentik_api_token>_ has to be replaced with API token of that user.

**Access to Kentik API must be allowed from the external IP address of the Docker container**.
```shell
docker run -d --name kentik_image_cache \
    --env KT_AUTH_EMAIL=<kentik_user_mail> \
    --env KT_AUTH_TOKEN=<kentik_api_token> \
    -v /opt/kentik_image_cache:/cache -p 80:80 kentik_image_cache
```

Credentials and other configuration information can be also provided via environment file:
```shell
echo "KT_AUTH_EMAIL=<kentik_user_mail>" > .env
echo "KT_AUTH_TOKEN=<kentik_api_token>" >> .env
docker run -d --name kentik_image_cache --env-file .env \
           -v /opt/kentik_image_cache:/cache -p 80:80 kentik_image_cache
```
### Local deployment for development
The bellow procedure assumes:
- Unix/Linux-like operating system
- functional `git` installation
- Python 3.8 or newer installed as `python3`

#### Clone repo to local disk:
```shell
git clone https://github.com/kentik/kentik_image_cache.git
```

#### Create virtual environment
```shell
cd kentik_image_cache
python3 -m venv venv
```

#### Install dependencies
```shell
venv/bin/pip3 install -r requirements.txt
```

#### Create cache directory
_Note_: the cache directory **must not** be in the repo tree in order for the `uvicorn --reload` feature to work correctly.
```shell
mkdir /tmp/cache
```

#### Create environment file with Kentik credentials
```shell
echo "KT_AUTH_EMAIL=<kentik_user_mail>" > .env
echo "KT_AUTH_TOKEN=<kentik_api_token>" >> .env
echo "CACHE_PATH=/tmp/cache" >> .env
```

#### Start the server with debug messages enabled and in self-reload mode
```shell
DEBUG=1 venv/bin/uvicorn app.main:app --reload
```

#### Test access
- API spec and tester: http://127.0.0.1:8000/docs
- Cache content info:  http://127.0.0.1:8000/info

## Testing

Simple integration test script `tests/run_tests.py` can be used to test a fully configured instance
of the image cache (it must have nertwork access and valid credentials to access Kentik API).
The test script (by default) uses requests stored in `tests/data`.

Example of running all test requests concurrently against URL `http://127.0.0.1:8000`:

```shell
tests/run_tests.py --concurrent --url http://127.0.0.1:8000
2021-05-27 23:00:53 Using URL: http://127.0.0.1:8000
2021-05-27 23:00:53 tid: 0 loading request from: tests/data/bad_query.json
2021-05-27 23:00:53 tid: 1 loading request from: tests/data/example_query_1.json
2021-05-27 23:00:53 tid: 2 loading request from: tests/data/example_query_2.json
2021-05-27 23:00:53 tid: 3 loading request from: tests/data/example_query_3.json
2021-05-27 23:00:53 tid: 4 loading request from: tests/data/example_query_4.json
2021-05-27 23:00:53 5 requests loaded
2021-05-27 23:00:53 Running tests concurrently
2021-05-27 23:00:53 tid: 0 posting request
2021-05-27 23:00:53 tid: 1 posting request
2021-05-27 23:00:53 tid: 2 posting request
2021-05-27 23:00:53 tid: 3 posting request
2021-05-27 23:00:53 tid: 4 posting request
2021-05-27 23:00:53 tid: 0: got id: 53693a077a6e1eec6407df161ae964d34170a7743e67488b0ece175005ac69aa_1622181773.873009
2021-05-27 23:00:53 tid: 2: got id: d8e8c3038d31e454971f6a067a4190d9a34f9d1a8415ff3260939a0ca53e6436_1622181953.864447
2021-05-27 23:00:53 tid: 3: got id: 4f2278d1a4d4d5a202a9972027d05e9ac13032b00282b5c2b67a79b60002cb7c_1622181773.848177
2021-05-27 23:00:53 tid: 3 requesting: http://127.0.0.1:8000/image/4f2278d1a4d4d5a202a9972027d05e9ac13032b00282b5c2b67a79b60002cb7c_1622181773.848177
2021-05-27 23:00:53 tid: 0 requesting: http://127.0.0.1:8000/image/53693a077a6e1eec6407df161ae964d34170a7743e67488b0ece175005ac69aa_1622181773.873009
2021-05-27 23:00:53 tid: 1: got id: fbdaa71df680024289416c97b392d55c2ce218e8a69054ff084f032bbfb3f867_1622182253.88189
2021-05-27 23:00:53 tid: 1 requesting: http://127.0.0.1:8000/image/fbdaa71df680024289416c97b392d55c2ce218e8a69054ff084f032bbfb3f867_1622182253.88189
2021-05-27 23:00:53 tid: 2 requesting: http://127.0.0.1:8000/image/d8e8c3038d31e454971f6a067a4190d9a34f9d1a8415ff3260939a0ca53e6436_1622181953.864447
2021-05-27 23:00:53 tid: 4: got id: 5d8ed88d722d32ca3b42883671a27a7cbd76140bf8b154dc471936b291118d1c_1622181713.891764
2021-05-27 23:00:53 tid: 4 requesting: http://127.0.0.1:8000/image/5d8ed88d722d32ca3b42883671a27a7cbd76140bf8b154dc471936b291118d1c_1622181713.891764
2021-05-27 23:00:54 tid: 0 got: status: 400 type: application/json length: 194
2021-05-27 23:01:01 tid: 1 got: status: 200 type: image/png length: 61117
2021-05-27 23:01:01 tid: 2 got: status: 200 type: image/png length: 71561
2021-05-27 23:01:02 tid: 3 got: status: 200 type: image/png length: 147938
2021-05-27 23:01:04 tid: 4 got: status: 200 type: application/pdf length: 73343
```

Example of running all tests matching `example_*.json` sequentially against `http://127.0.0.1:8000`:

```shell
tests/run_tests.py --glob 'example_*.json' --url http://127.0.0.1:8000
2021-05-27 22:59:21 Using URL: http://127.0.0.1:8000
2021-05-27 22:59:21 tid: 0 loading request from: tests/data/example_query_1.json
2021-05-27 22:59:21 tid: 1 loading request from: tests/data/example_query_2.json
2021-05-27 22:59:21 tid: 2 loading request from: tests/data/example_query_3.json
2021-05-27 22:59:21 tid: 3 loading request from: tests/data/example_query_4.json
2021-05-27 22:59:21 4 requests loaded
2021-05-27 22:59:21 Running tests
2021-05-27 22:59:21 tid: 0 posting request
2021-05-27 22:59:22 tid: 0: got id: fbdaa71df680024289416c97b392d55c2ce218e8a69054ff084f032bbfb3f867_1622182162.004539
2021-05-27 22:59:22 tid: 0 requesting: http://127.0.0.1:8000/image/fbdaa71df680024289416c97b392d55c2ce218e8a69054ff084f032bbfb3f867_1622182162.004539
2021-05-27 22:59:28 tid: 0 got: status: 200 type: image/png length: 60706
2021-05-27 22:59:28 tid: 1 posting request
2021-05-27 22:59:28 tid: 1: got id: d8e8c3038d31e454971f6a067a4190d9a34f9d1a8415ff3260939a0ca53e6436_1622181868.80616
2021-05-27 22:59:28 tid: 1 requesting: http://127.0.0.1:8000/image/d8e8c3038d31e454971f6a067a4190d9a34f9d1a8415ff3260939a0ca53e6436_1622181868.80616
2021-05-27 22:59:37 tid: 1 got: status: 200 type: image/png length: 72078
2021-05-27 22:59:37 tid: 2 posting request
2021-05-27 22:59:37 tid: 2: got id: 4f2278d1a4d4d5a202a9972027d05e9ac13032b00282b5c2b67a79b60002cb7c_1622181697.10503
2021-05-27 22:59:37 tid: 2 requesting: http://127.0.0.1:8000/image/4f2278d1a4d4d5a202a9972027d05e9ac13032b00282b5c2b67a79b60002cb7c_1622181697.10503
2021-05-27 22:59:46 tid: 2 got: status: 200 type: image/png length: 146699
2021-05-27 22:59:46 tid: 3 posting request
2021-05-27 22:59:46 tid: 3: got id: 5d8ed88d722d32ca3b42883671a27a7cbd76140bf8b154dc471936b291118d1c_1622181646.687514
2021-05-27 22:59:46 tid: 3 requesting: http://127.0.0.1:8000/image/5d8ed88d722d32ca3b42883671a27a7cbd76140bf8b154dc471936b291118d1c_1622181646.687514
2021-05-27 22:59:56 tid: 3 got: status: 200 type: application/pdf length: 72974
```

Full usage help:
```
tests/run_tests.py --help
Usage: run_tests.py [OPTIONS]

Options:
  --url TEXT    URL to test against  [default: http://127.0.0.1]
  --dir TEXT    Directory to load requests from  [default: tests/data]
  --glob TEXT   Globbing pattern for request files  [default: *.json]
  --concurrent  Run requests concurrently  [default: False]
  --help        Show this message and exit.
```

_Note_: Full unit test suite is in development.