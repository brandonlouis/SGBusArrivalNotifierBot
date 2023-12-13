import requests

def get_data(busStopCode):
    url = "https://arrivelah2.busrouter.sg/"
    response = requests.get(url, params={"id": busStopCode})

    return response.json()