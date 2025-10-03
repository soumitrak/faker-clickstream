import hashlib
import random
import re
import string
from datetime import datetime, timedelta
from random import choice, randint

import numpy as np
from faker.providers import BaseProvider

from faker_clickstream.event_constants import weighted_events, events, channel
from faker_clickstream.ip import ip_list
from faker_clickstream.mobile_phones import mobile_phones
from faker_clickstream.user_agents import user_agents


class ClickstreamProvider(BaseProvider):
    """
        A Provider for clickstream related test data.

        >>> from faker import Faker
        >>> from faker_clickstream import ClickstreamProvider
        >>> fake = Faker()
        >>> fake.add_provider(ClickstreamProvider)
        >>> fake.session_clickstream()
    """

    def user_agent(self):
        """
        Generate random user agent.

        :return: User agent string
        """
        return choice(user_agents)

    def event(self):
        """
        Generate random event type name for e-commerce site.

        :return: Event type string
        """
        return choice(events)

    def weighted_event(self):
        """
        Generate a random event object according to popularity weight. Higher popularity increases the
        chances of occurrence.

        :return: Event object (JSON)
        """
        return random.choices(weighted_events, weights=[e['popularity'] for e in weighted_events], k=1)[0]

    def session_clickstream(self, rand_session_max_size: int = 25, max_product_code: int = 999999, max_order_id: int = 999999, max_user_id: int = 999999, start_time: str = "0s", a: float = 1.5):
        """
        Generate session clickstream events.

        :param rand_session_max_size: Max number of possible events in session. Defaults to 25.
        :param max_product_code: Max value for product codes. Defaults to 999999.
        :param max_order_id: Max value for order IDs. Defaults to 999999.
        :param max_user_id: Max value for user IDs. Defaults to 999999.
        :param start_time: Start time offset from current time (e.g., "-1d", "-1h", "+1m", "0s"). Defaults to "0s".
        :param a: Shape parameter for Pareto distribution. Defaults to 1.5.
        :return: List of session events
        """

        # Initialize static session values
        session_events = []
        user_id = _get_user_id(end=max_user_id)
        user_agent = self.user_agent()
        session_id = _get_session_id()
        ip = _get_ip()
        channel_type = _get_channel()
        random_session_size = randint(1, rand_session_max_size)

        # Parse start_time and calculate the base event time
        start_offset_seconds = _parse_time_interval(start_time)
        current_event_time = datetime.now() + timedelta(seconds=start_offset_seconds)

        # Keep track of unique values in a session
        unique_session_events = set()
        product_codes = set()

        for s in range(random_session_size):
            # Format current event time
            event_time = _format_time(current_event_time)

            # Generate next event time offset using Pareto distribution
            if s < random_session_size - 1:
                pareto_offset = np.random.pareto(a)
                current_event_time = current_event_time + timedelta(seconds=pareto_offset)

            # Fetch weighted event
            event = self.weighted_event()

            if (event['name'] == 'Login' and event['name'] in unique_session_events) \
                    or (event['name'] == 'CheckoutAsGuest' and user_id != 0):
                # If user ID is not 0, discard CheckoutAsGuest event
                # or Login exists in session, discard Login event
                # Add a mock Search event
                event['name'] = 'Search'

            if event['name'] == 'Login' and user_id == 0:
                # If user id is -1 and Login event, regenerate user ID.
                user_id = _get_user_id(start=1, end=max_user_id)

            if (event['name'] == 'Login' and user_id != 0) or (event['name'] == 'Logout' and user_id == 0):
                # Add a mock Search event
                event['name'] = 'Search'

            # Keep track of unique events in session
            unique_session_events.add(event['name'])

            # Handle event dependencies
            if len(event['dependsOn']):
                list_check = [d in unique_session_events for d in event['dependsOn']]
                if event['dependencyFilter'] == 'all':
                    f = all(list_check)
                else:
                    f = any(list_check)
                if not f:
                    # Add a mock Search event
                    event['name'] = 'Search'

            # If CompleteOrder, remove some events from the unique list to reoccur.
            if event['name'] == 'CompleteOrder':
                if 'Checkout' in unique_session_events:
                    unique_session_events.remove('Checkout')
                if 'CheckoutAsGuest' in unique_session_events:
                    unique_session_events.remove('CheckoutAsGuest')
                if 'DecreaseQuantity' in unique_session_events:
                    unique_session_events.remove('DecreaseQuantity')

            # Fill metadata object conditionally
            metadata = {}
            if event['name'] == 'Search':
                sample_product = _get_weighted_mobile_phone()
                metadata['query'] = choice(
                    (sample_product['model_name'], sample_product['brand_name'], sample_product['os'])
                )

            if event['name'] in ('AddToCart', 'IncreaseQuantity'):
                metadata['product_id'] = _get_product_code(max_product_code)
                metadata['quantity'] = _get_quantity()
                product_codes.add(metadata['product_id'])

            if event['name'] == 'DeleteFromCart':
                if len(product_codes):
                    random_delete = choice(list(product_codes))
                    product_codes.remove(random_delete)
                    metadata['product_id'] = random_delete

            if event['name'] == 'CheckOrderStatus':
                metadata['order_id'] = _get_order_id(max_order_id)

            # Construct final event object
            r = {
                "ip": ip,
                "user_id": user_id,
                "user_agent": user_agent,
                "session_id": session_id,
                "event_time": event_time,
                "event_name": event['name'],
                "channel": channel_type,
                "metadata": metadata
            }
            session_events.append(r)
        return session_events


def _parse_time_interval(interval: str):
    """
    Parse time interval string and convert to seconds.

    :param interval: Time interval string (e.g., "-1d", "-1h", "+1m", "0s")
    :return: Offset in seconds
    """
    match = re.match(r'^([+-]?)(\d+)([smhd])$', interval)
    if not match:
        raise ValueError(f"Invalid time interval format: {interval}. Expected format: [+/-]<number><unit> where unit is s/m/h/d")

    sign, value, unit = match.groups()
    value = int(value)

    # Convert to seconds
    unit_multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400
    }

    seconds = value * unit_multipliers[unit]

    # Apply sign
    if sign == '-':
        seconds = -seconds

    return seconds


def _get_session_id():
    """
    Generate session ID

    :return: Session ID string
    """
    return hashlib.sha256(
        ('%s%s%s' % (
            datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f"),
            (''.join(random.choice(string.ascii_lowercase)) for _ in range(10)),
            'faker_clickstream'
        )).encode('utf-8')
    ).hexdigest()


def _get_product_code(max_value: int = 999999):
    """
    Generate random product code from range 1 to max_value.

    :param max_value: Max value for product code. Defaults to 999999.
    :return: Random integer number
    """
    return randint(1, max_value)


def _get_order_id(max_value: int = 999999):
    """
    Generate random order id from range 1 to max_value.

    :param max_value: Max value for order ID. Defaults to 999999.
    :return: Random integer number
    """
    return randint(1, max_value)


def _get_user_id(start: int = 0, end: int = 999999):
    """
    Generate random user id from range start to end. Zero value may identify null user.

    :param start: Index start (Default: 0)
    :param end: Index end (Default: 999999)
    :return: Random integer number
    """
    return randint(start, end)


def _format_time(t):
    """
    Format time to string.

    :param t: Time object
    :return: Time string in format like 28/03/2022 23:22:15.360252
    """
    return t.strftime("%d/%m/%Y %H:%M:%S.%f")


def _get_quantity():
    """
    Get random product order quantity from 1 to 5. Values are given a weight, decreasing as the quantity number
    increases.

    :return: Product quantity number
    """
    return random.choices([1, 2, 3, 4, 5], weights=[50, 20, 20, 5, 5], k=1)[0]


def _get_weighted_mobile_phone():
    """
    Get mobile phone object according to popularity

    :return: Mobile phone object
    """
    return random.choices(mobile_phones, weights=[e['popularity'] for e in mobile_phones], k=1)[0]


def _get_ip():
    """
    Get random IP address from list.

    :return: IP address string
    """
    return choice(ip_list)


def _get_channel():
    """
    Get user origin channel (e.g. "Organic search", "Direct", "Social media", "Referral", "Other")

    :return: Origin channel string
    """
    return choice(channel)
