import logging
import swisseph as swe

from jyotisha.panchangam import temporal
from jyotisha.panchangam.spatio_temporal import City, Timezone

city = City.from_address_and_timezone(address="Mountain View, CA", timezone_str="America/Los_Angeles")
time = Timezone(city.timezone).local_time_to_julian_day(year=2019, month=1, day=21, hours=18, minutes=32, seconds=0)
logging.info(time)
temporal.print_angas_x_ayanamshas(jd=time)
