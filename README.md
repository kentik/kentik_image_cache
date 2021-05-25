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
  | STATUS_POLL_PERIOD  | no | Interval for polling for completion of cache entries | 3 seconds |
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
    while entry is pending
      wait for status_poll_period
    return 200 and image data to the client
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
_TDB_

## Testing
_TBD_

