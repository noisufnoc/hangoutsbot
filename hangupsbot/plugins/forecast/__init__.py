# coding: utf-8
"""
Use DarkSky.net to get current weather forecast for a given location.

Instructions:
    * Get an API key from https://darksky.net/dev/
    * Store API key in config.json:forecast_api_key
"""
import logging
from decimal import Decimal

import aiohttp

from hangupsbot import plugins


logger = logging.getLogger(__name__)
_INTERNAL = {}

HELP = {
    'setweatherlocation': _('Sets the Lat Long default coordinates for this '
                            'hangout when polling for weather data\n'
                            '{bot_cmd} setWeatherLocation <location>'),

    'weather': _("Returns weather information from darksky.net\n"
                 " <b>{bot_cmd} weather <location></b>\n"
                 "   Get location's current weather.\n"
                 " <b>{bot_cmd} weather</b>\n"
                 "   Get the hangouts default location's current weather. If "
                 "the  default location is not set talk to a hangout admin."),

    'forecast': _("Returns a brief textual forecast from darksky.net\n"
                  " <b>{bot_cmd} weather <location></b>\n"
                  "   Get location's current forecast.\n"
                  " <b>{bot_cmd} weather</b>\n"
                  "   Get the hangouts default location's forecast. If default "
                  "location is not set talk to a hangout admin."),
}


def _initialize(bot):
    api_key = bot.config.get_option('forecast_api_key')
    if api_key:
        _INTERNAL['forecast_api_key'] = api_key
        plugins.register_user_command([
            'weather',
            'forecast',
        ])
        plugins.register_admin_command([
            'setweatherlocation',
        ])
        plugins.register_help(HELP)
    else:
        logger.debug('WEATHER: config["forecast_api_key"] required')


async def setweatherlocation(bot, event, *args):
    """Sets the Lat Long default coordinates for this hangout"""
    location = ''.join(args).strip()
    if not location:
        return _('No location was specified, please specify a location.')

    location = await _lookup_address(location)
    if location is None:
        return _('Unable to find the specified location.')

    if not bot.memory.exists(["conv_data", event.conv.id_]):
        bot.memory.set_by_path(['conv_data', event.conv.id_], {})

    bot.memory.set_by_path(
        ["conv_data", event.conv.id_, "default_weather_location"],
        {'lat': location['lat'], 'lng': location['lng']})
    bot.memory.save()
    return _('This hangouts default location has been set to {}.').format(
        location)


async def weather(bot, event, *args):
    """Returns weather information from darksky.net"""
    weather_data = await _get_weather(bot, event, args)
    if weather_data:
        return _format_current_weather(weather_data)
    return _(
        'There was an error retrieving the weather, guess you need to look '
        'outside.')


async def forecast(bot, event, *args):
    """Returns a brief textual forecast from darksky.net"""
    weather_data = await _get_weather(bot, event, args)
    if weather_data:
        return _format_forecast_weather(weather_data)
    return _(
        'There was an error retrieving the weather, guess you need to look '
        'outside.')


def _format_current_weather(weather_data):
    """
    Formats the current weather data for the user.
    """
    weather_lines = []
    if 'temperature' in weather_data:
        weather_lines.append("It is currently: <b>{0}°{1}</b>".format(
            round(weather_data['temperature'], 2),
            weather_data['units']['temperature']))
    if 'summary' in weather_data:
        weather_lines.append("<i>{0}</i>".format(weather_data['summary']))
    if 'feelsLike' in weather_data:
        weather_lines.append(
            "Feels Like: {0}°{1}".format(round(weather_data['feelsLike'], 2),
                                         weather_data['units']['temperature']))
    if 'windspeed' in weather_data:
        weather_lines.append(
            "Wind: {0} {1} from {2}".format(round(weather_data['windspeed'], 2),
                                            weather_data['units']['windSpeed'],
                                            _get_wind_direction(
                                                weather_data['windbearing'])))
    if 'humidity' in weather_data:
        weather_lines.append("Humidity: {0}%".format(weather_data['humidity']))
    if 'pressure' in weather_data:
        weather_lines.append(
            "Pressure: {0} {1}".format(round(weather_data['pressure'], 2),
                                       weather_data['units']['pressure']))

    return "\n".join(weather_lines)


def _format_forecast_weather(weather_data):
    """
    Formats the forecast data for the user.
    """
    weather_lines = []
    if 'hourly' in weather_data:
        weather_lines.append(
            "<b>Next 24 Hours</b>\n{}".format(weather_data['hourly']))
    if 'daily' in weather_data:
        weather_lines.append(
            "<b>Next 7 Days</b>\n{}".format(weather_data['daily']))

    return "\n".join(weather_lines)


async def _lookup_address(location):
    """
    Retrieve the coordinates of the location from googles geocode api.
    Limit of 2,000 requests a day
    """
    google_map_url = 'https://maps.googleapis.com/maps/api/geocode/json'
    payload = {'address': location}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(google_map_url,
                                   params=payload) as response:
                response.raise_for_status()
                raw = await response.json()
    except aiohttp.ClientError as err:
        logger.info('lookup_address %s: %r', id(payload), location)
        logger.error('lookup_address %s: request failed: %r', id(payload), err)
        return None

    try:
        results = raw['results'][0]
        return {
            'lat': results['geometry']['location']['lat'],
            'lng': results['geometry']['location']['lng'],
            'address': results['formatted_address'],
        }
    except (IndexError, KeyError) as err:
        logger.info('lookup_address %s: %r', id(payload), raw)
        logger.error('lookup_address %s: parse error %r', id(payload), err)
        return None


async def _lookup_weather(coordinates):
    """
    Retrieve the current forecast for the specified coordinates from darksky.net
    Limit of 1,000 requests a day
    """

    forecast_io_url = ('https://api.darksky.net/forecast/{0}/{1},'
                       '{2}?units=auto').format(_INTERNAL['forecast_api_key'],
                                                coordinates['lat'],
                                                coordinates['lng'])
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(forecast_io_url) as response:
                response.raise_for_status()
                raw = await response.json()
    except aiohttp.ClientError as err:
        logger.info('lookup_weather %s: %r', id(err), coordinates)
        logger.error('lookup_weather %s: request failed: %r', id(err), err)
        return None

    try:
        current = {
            'time': raw['currently']['time'],
            'summary': raw['currently']['summary'],
            'temperature': Decimal(raw['currently']['temperature']),
            'feelsLike': Decimal(raw['currently']['apparentTemperature']),
            'units': _get_forecast_units(raw),
            'humidity': int(raw['currently']['humidity'] * 100),
            'windspeed': Decimal(raw['currently']['windSpeed']),
            'windbearing': raw['currently']['windBearing'],
            'pressure': raw['currently']['pressure'],
        }
        if current['units']['pressure'] == 'kPa':
            current['pressure'] = Decimal(current['pressure'] / 10)

        if 'hourly' in raw:
            current['hourly'] = raw['hourly']['summary']
        if 'daily' in raw:
            current['daily'] = raw['daily']['summary']

    except (ValueError, KeyError) as err:
        logger.info('lookup_weather %s: %r', id(err), coordinates)
        logger.error('lookup_weather %s: parse error: %r', id(err), err)
        current = dict()

    return current


async def _get_weather(bot, event, params):
    """
    Checks memory for a default location set for the current hangout.
    If one is not found and parameters were specified attempts to look up a
    location.
    If it finds a location it then attempts to load the weather data
    """
    parameters = list(params)
    location = {}

    if not parameters:
        if bot.memory.exists(["conv_data", event.conv.id_]):
            if bot.memory.exists(
                    ["conv_data", event.conv.id_, "default_weather_location"]):
                location = bot.memory.get_by_path(
                    ["conv_data", event.conv.id_, "default_weather_location"])
    else:
        address = ''.join(parameters).strip()
        location = await _lookup_address(address)

    if location:
        return await _lookup_weather(location)

    return {}


def _get_forecast_units(result):
    """
    Checks to see what uni the results were passed back as and sets the
    display units accordingly
    """
    units = {
        'temperature': 'F',
        'distance': 'Miles',
        'percipIntensity': 'in./hr.',
        'precipAccumulation': 'inches',
        'windSpeed': 'mph',
        'pressure': 'millibars',
    }
    if result['flags']:
        unit = result['flags']['units']
        if unit != 'us':
            units['temperature'] = 'C'
            units['distance'] = 'KM'
            units['percipIntensity'] = 'milimeters per hour'
            units['precipAccumulation'] = 'centimeters'
            units['windSpeed'] = 'm/s'
            units['pressure'] = 'kPa'
            if unit == 'ca':
                units['windSpeed'] = 'km/h'
            if unit == 'uk2':
                units['windSpeed'] = 'mph'
                units['distance'] = 'Miles'
    return units


def _get_wind_direction(degrees):
    """
    Determines the direction the wind is blowing from based off the degree
    passed from the API
    0 degrees is true north
    """
    direction_text = "N"
    if 5 <= degrees < 40:
        direction_text = "NNE"
    elif 40 <= degrees < 50:
        direction_text = "NE"
    elif 50 <= degrees < 85:
        direction_text = "ENE"
    elif 85 <= degrees < 95:
        direction_text = "E"
    elif 95 <= degrees < 130:
        direction_text = "ESE"
    elif 130 <= degrees < 140:
        direction_text = "SE"
    elif 140 <= degrees < 175:
        direction_text = "SSE"
    elif 175 <= degrees < 185:
        direction_text = "S"
    elif 185 <= degrees < 220:
        direction_text = "SSW"
    elif 220 <= degrees < 230:
        direction_text = "SW"
    elif 230 <= degrees < 265:
        direction_text = "WSW"
    elif 265 <= degrees < 275:
        direction_text = "W"
    elif 275 <= degrees < 310:
        direction_text = "WNW"
    elif 310 <= degrees < 320:
        direction_text = "NW"
    elif 320 <= degrees < 355:
        direction_text = "NNW"

    return direction_text
