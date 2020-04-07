#!/usr/bin/env python3

import argparse
from pathlib import Path
import requests
import sys
import tidalapi
from tqdm import tqdm
import yaml

def track_file_name(track):
    return "{} - {}{}.{}".format(track.artist.name, track.name, " (%)"%track.version if track.version else "", "m4a")

def download_track(tidal_session, track, folder):
    file_path = Path(folder) / track_file_name(track)
    if file_path.exists():
        return
    data = requests.get(tidal_session.get_media_url(track.id))
    with tqdm.wrapattr(open(file_path, 'wb+'), "write", miniters=1, desc = "Downloading {}".format(str(file_path.name))) as fout:
        for chunk in requests.get(tidal_session.get_media_url(track.id)):
            fout.write(chunk)

def open_tidal_session(config):
    session = tidalapi.Session()
    session.login(config['username'], config['password'])
    return session

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('uri', help='URI of the song or playlist to download')
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--output_folder', help='Folder to save the file to', default=Path.cwd())
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    tidal_session = open_tidal_session(config['tidal'])
    if not tidal_session.check_login():
        sys.exit("Could not connect to Tidal")
    if not Path(args.output_folder).exists():
        sys.exit("Path '{}' does not exist".format(args.output_folder))
    id = args.uri.split('/')[-1]
    if '-' in id:
        sys.error("Playlists are not currently supported")
    else:
        track = tidal_session.get_track(id)
        download_track(tidal_session, track, args.output_folder)
