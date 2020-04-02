#!/usr/bin/env python3

import argparse
import requests
import sys
import spotipy
import tidalapi
import time
from urllib.parse import urljoin
import yaml

def simple(input_string):
    # only take the first part of a string before any hyphens or brackets to account for different versions
    return input_string.split('-')[0].strip().split('(')[0].strip().split('[')[0].strip()

def duration_match(tidal_track, spotify_track, tolerance=2):
    # the duration of the two tracks must be the same to within 2 seconds
    return abs(tidal_track.duration - spotify_track['duration_ms']/1000) < tolerance

def name_match(tidal_track, spotify_track):
    def exclusion_rule(pattern, tidal_track, spotify_track):
        spotify_has_pattern = pattern in spotify_track['name'].lower()
        tidal_has_pattern = pattern in tidal_track.name.lower() or (not tidal_track.version is None and (pattern in tidal_track.version.lower()))
        return spotify_has_pattern != tidal_has_pattern

    # handle some edge cases
    if exclusion_rule("instrumental", tidal_track, spotify_track): return False
    if exclusion_rule("acapella", tidal_track, spotify_track): return False
    if exclusion_rule("remix", tidal_track, spotify_track): return False

    # the simplified version of the Spotify track name must be a substring of the Tidal track name
    simple_spotify_track = simple(spotify_track['name'].lower()).split('feat.')[0].strip()
    return simple_spotify_track in tidal_track.name.lower()

def artist_match(tidal_track, spotify_track):
    def split_artist_name(artist):
       if '&' in artist:
           return artist.split('&')
       elif ',' in artist:
           return artist.split(',')
       else:
           return [artist]

    def get_tidal_artists(tidal_track):
        result = []
        for artist in tidal_track.artists:
            result.extend(split_artist_name(artist.name))
        return set([simple(x.strip().lower()) for x in result])

    def get_spotify_artists(spotify_track):
        result = []
        for artist in spotify_track['artists']:
            result.extend(split_artist_name(artist['name']))
        return set([simple(x.strip().lower()) for x in result])
    # There must be at least one overlapping artist between the Tidal and Spotify track
    return get_tidal_artists(tidal_track).intersection(get_spotify_artists(spotify_track)) != set()
  
def match(tidal_track, spotify_track):
    return duration_match(tidal_track, spotify_track) and name_match(tidal_track, spotify_track) and artist_match(tidal_track, spotify_track)

def tidal_search(tidal_session, spotify_track):
    # search for album name and first album artist
    if 'album' in spotify_track and 'artists' in spotify_track['album'] and len(spotify_track['album']['artists']):
        album_result = tidal_session.search('album', simple(spotify_track['album']['name']) + " " + simple(spotify_track['album']['artists'][0]['name']))
        for album in album_result.albums:
            album_tracks = tidal_session.get_album_tracks(album.id)
            if len(album_tracks) >= spotify_track['track_number']:
                track = album_tracks[spotify_track['track_number'] - 1]
                if match(track, spotify_track):
                    return track
    # if that fails then search for track name and first artist
    for track in tidal_session.search('track', simple(spotify_track['name']) + ' ' + simple(spotify_track['artists'][0]['name'])).tracks:
        if match(track, spotify_track):
            return track

def get_tidal_playlists_dict(tidal_session):
    # a dictionary of name --> playlist
    tidal_playlists = tidal_session.get_user_playlists(tidal_session.user.id)
    return {playlist.name: playlist for playlist in tidal_playlists}

def set_tidal_playlist(session, playlist_id, track_ids):
    chunk_size = 25 # add/delete tracks in chunks of no more than this many tracks

    # erases any items in the given playlist, then adds all of the tracks given in track_ids
    # had to hack this together because the API doesn't include it
    request_params = {
        'sessionId': session.session_id,
        'countryCode': session.country_code,
        'limit': '999',
    }
    def get_headers():
        etag = session.request('GET','playlists/%s/tracks' % playlist_id).headers['ETag']
        return {'if-none-match' : etag}
    # clear all old items from playlist
    while True:
        playlist = session.get_playlist(playlist_id)
        if not playlist.num_tracks:
            break
        track_index_string = ",".join([str(x) for x in range(min(chunk_size, playlist.num_tracks))])
        url = urljoin(session._config.api_location, 'playlists/{}/tracks/{}'.format(playlist.id, track_index_string))
        result = requests.request('DELETE', url, params=request_params, headers=get_headers())
        result.raise_for_status()
    # add all new items to the playlist
    offset = 0
    while offset < len(track_ids):
        data = {
            'trackIds' : ",".join([str(x) for x in track_ids[offset:offset+chunk_size]]),
            'toIndex' : offset
        }
        offset += chunk_size
        url = urljoin(session._config.api_location, 'playlists/{}/tracks'.format(playlist.id))
        result = requests.request('POST', url, params=request_params, data=data, headers=get_headers())
        result.raise_for_status()

def create_tidal_playlist(session, name):
    result = session.request('POST','users/%s/playlists' % session.user.id ,data={'title': name})
    return session.get_playlist(result.json()['uuid'])

def repeat_on_exception(function, *args, remaining=5):
    # utility to repeat calling the function up to 5 times if an exception is thrown
    try:
        function(*args)
    except:
        if not remaining:
            print("Repeated error calling the function '{}' with the following arguments:".format(function.__name__))
            print(args)
            raise
        time.sleep(5)
        repeat_on_exception(function, *args, remaining=remaining-1)

def sync_playlist(spotify_session, tidal_session, spotify_playlist, tidal_playlist):
    source_results = spotify_session.playlist_tracks(spotify_playlist['id'], fields="next,items(track(name,album(name,artists),artists,track_number,duration_ms,id))")
    tidal_track_ids = []
    while True:
        for source_result in source_results['items']:
            source_track = source_result['track']
            result = tidal_search(tidal_session, source_track)
            if result:
                tidal_track_ids.append(result.id)
                print("Found track: {} - {}{}".format(result.artist.name, result.name, " ({})".format(result.version) if result.version else ""), end='\r')
                sys.stdout.write("\033[K")
            else:
                color = ('\033[91m', '\033[0m')
                print(color[0] + "Could not find track {}: {} - {}".format(source_track['id'], ",".join([a['name'] for a in source_track['artists']]), source_track['name']) + color[1])

        # move to the next page of results if there are still tracks remaining in the playlist
        if source_results['next']:
            source_results = spotify_session.next(source_results)
        else:
            break
    #print("Adding the following track IDs to the playlist:")
    #print(tidal_track_ids)
    repeat_on_exception(set_tidal_playlist, tidal_session, tidal_playlist.id, tidal_track_ids)

def open_spotify_session(config):
    credentials_manager = spotipy.SpotifyOAuth(username=config['username'],
				       scope='playlist-read-private',
				       client_id=config['client_id'],
				       client_secret=config['client_secret'],
				       redirect_uri='http://localhost:{}/callback'.format(config['port']))
    try:
        credentials_manager.get_access_token(as_dict=False)
    except spotipy.SpotifyOauthError:
        sys.exit("Error opening Spotify sesion; could not get token for username: ".format(config['username']))

    return spotipy.Spotify(oauth_manager=credentials_manager)

def open_tidal_session(config):
    session = tidalapi.Session()
    session.login(config['username'], config['password'])
    return session

def sync_list(spotify_session, tidal_session, playlists):
    tidal_playlists = get_tidal_playlists_dict(tidal_session)
    for spotify_id, tidal_id in playlists:
        try:
            spotify_playlist = spotify_session.playlist(spotify_id)
        except spotipy.SpotifyException as e:
            print("Error getting Spotify playlist " + spotify_id)
            print(e)
            continue
        if tidal_id:
            # if the user manually specified the id of a Tidal playlist to use then favour that
            try:
                tidal_playlist = tidal_session.get_playlist(tidal_id)
            except exception:
                print("Error getting Tidal playlist " + tidal_id)
                print(e)
                continue
        elif spotify_playlist['name'] in tidal_playlists:
            # if there's an existing tidal playlist with the name of the current playlist then use that
            tidal_playlist = tidal_playlists[spotify_playlist['name']]
        else:
            # otherwise create a new playlist
            tidal_playlist = create_tidal_playlist(tidal_session, spotify_playlist['name'])
        print("")
        print("Syncing playlist: {} --> {}".format(spotify_playlist['name'], tidal_playlist.name))
        sync_playlist(spotify_session, tidal_session, spotify_playlist, tidal_playlist)

def get_playlists_from_spotify(spotify_session, config):
    # get all the user playlists from the Spotify account
    playlists = []
    spotify_results = spotify_session.user_playlists(config['spotify']['username'])
    exclude_list = set([x.split(':')[-1] for x in config.get('excluded_playlists', [])])
    while True:
        for spotify_playlist in spotify_results['items']:
            if spotify_playlist['owner']['id'] == config['spotify']['username'] and not spotify_playlist['id'] in exclude_list:
                playlists.append((spotify_playlist['id'], None))
        # move to the next page of results if there are still playlists remaining
        if spotify_results['next']:
            spotify_results = spotify_session.next(spotify_results)
        else:
            break
    return playlists

def get_playlists_from_config(config):
    # get the list of playlist sync mappings from the configuration file
    return [(item['spotify_id'], item['tidal_id']) for item in config['sync_playlists']]

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--uri', help='synchronize a specific URI instead of the one in the config')
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    spotify_session = open_spotify_session(config['spotify'])
    tidal_session = open_tidal_session(config['tidal'])
    if not tidal_session.check_login():
        sys.exit("Could not connect to Tidal")
    if args.uri:
        # if a playlist ID is explicitly provided as a command line argument then use that
        sync_list(spotify_session, tidal_session, [(args.uri, None)])
    elif config.get('sync_playlists', None):
        # if the config contains a sync_playlists list of mappings then use that
        sync_list(spotify_session, tidal_session, get_playlist_from_config(config))
    else:
        # otherwise just use the user playlists in the Spotify account
        sync_list(spotify_session, tidal_session, get_playlists_from_spotify(spotify_session, config))
