#!/usr/bin/env python3

import argparse
from pathlib import Path
import requests
import sys
import tidalapi
from tqdm import tqdm
import yaml

def track_file_name(track, url):
    source_extension = url.split('/')[-1].split('?')[0].split('.')[-1]
    extension = 'm4a' if source_extension == 'mp4' else source_extension
    return "{} - {}{}.{}".format(track.artist.name, track.name, " (%)"%track.version if track.version else "", extension)

def download_track(tidal_session, track, folder):
    media_url = tidal_session.get_media_url(track.id)
    file_path = Path(folder) / track_file_name(track, media_url)
    if file_path.exists():
        return
    with tqdm.wrapattr(open(file_path, 'wb+'), "write", miniters=1, desc = "Downloading {}".format(str(file_path.name))) as fout:
        for chunk in requests.get(media_url):
            fout.write(chunk)

def open_tidal_session(config):
    quality_mapping = {'low': tidalapi.Quality.low, 'high': tidalapi.Quality.high, 'lossless': tidalapi.Quality.lossless}
    quality = quality_mapping[config.get('quality', 'high').lower()]
    session = tidalapi.Session(tidalapi.Config(quality=quality))
    session.login(config['username'], config['password'])
    return session

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('uri', help='URI of the song or playlist to download')
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--output_folder', help='Folder to save the file to')
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    tidal_session = open_tidal_session(config['tidal'])
    output_folder = args.output_folder if args.output_folder else config.get('save_path', Path.cwd())
    if not tidal_session.check_login():
        sys.exit("Could not connect to Tidal")
    if not Path(output_folder).exists():
        sys.exit("Path '{}' does not exist".format(output_folder))
    id = args.uri.split('/')[-1]
    if '-' in id:
        sys.error("Playlists are not currently supported")
    else:
        track = tidal_session.get_track(id)
        download_track(tidal_session, track, output_folder)
