import logging

from jyotisha.panchangam.temporal import zodiac


def test_get_ayanamsha():
    ayanamsha = zodiac.Ayanamsha(ayanamsha_id=zodiac.Ayanamsha.CHITRA_AT_180)
    assert ayanamsha.get_offset(2458434.083333251) == 24.120535828308334


def test_swe_ayanamsha_api():
    import swisseph as swe
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    # city = City.from_address_and_timezone('Cupertino, CA', "America/Los_Angeles")
    # jd = city.local_time_to_julian_day(year=2018, month=11, day=11, hours=6, minutes=0, seconds=0)
    assert swe.get_ayanamsa(2458434.083333251) == 24.120535828308334


