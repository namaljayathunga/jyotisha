import logging
import os
import swisseph as swe
import sys
import traceback

from datetime import datetime
from math import floor
from typing import List
from itertools import filterfalse

from indic_transliteration import xsanscript as sanscript
from pytz import timezone as tz
from sanskrit_data.schema.common import JsonObject

import jyotisha.panchangam.temporal.hour
from jyotisha.panchangam import temporal, spatio_temporal
from jyotisha.panchangam.temporal import zodiac
from jyotisha.panchangam.temporal.festival import read_old_festival_rules_dict
from sanskrit_data.schema import common
from scipy.optimize import brentq

import jyotisha.panchangam
import jyotisha.panchangam.temporal.zodiac
from jyotisha.panchangam.spatio_temporal import CODE_ROOT, daily, CALC_RISE, CALC_SET


class Panchangam(common.JsonObject):
    """This class enables the construction of a panchangam for arbitrary periods, with festivals.
      """

    def __init__(self, city, start_date, end_date, script=sanscript.DEVANAGARI, fmt='hh:mm', ayanamsha_id=zodiac.Ayanamsha.CHITRA_AT_180,
                 compute_lagnams=False):
        """Constructor for the panchangam.
        :param compute_lagnams:
        :param compute_lagnams:
            """
        super(Panchangam, self).__init__()
        self.city = city
        self.start_date = tuple([int(x) for x in start_date.split('-')])  # (tuple of (yyyy, mm, dd))
        self.end_date = tuple([int(x) for x in end_date.split('-')])  # (tuple of (yyyy, mm, dd))
        self.script = script
        self.fmt = fmt

        self.jd_start_utc = temporal.utc_gregorian_to_jd(self.start_date[0], self.start_date[1], self.start_date[2], 0)
        self.jd_end_utc = temporal.utc_gregorian_to_jd(self.end_date[0], self.end_date[1], self.end_date[2], 0)

        self.duration = int(self.jd_end_utc - self.jd_start_utc) + 1
        self.len = int(self.duration + 4)  # some buffer, for various look-ahead calculations

        self.weekday_start = swe.day_of_week(self.jd_start_utc) + 1
        # swe has Mon = 0, non-intuitively!

        self.ayanamsha_id = ayanamsha_id
        
        self.add_details(compute_lagnams=compute_lagnams)

    def compute_angams(self, compute_lagnams=True):
        """Compute the entire panchangam
        """

        nDays = self.len

        # INITIALISE VARIABLES
        self.jd_midnight = [None] * nDays
        self.jd_sunrise = [None] * nDays
        self.jd_sunset = [None] * nDays
        self.jd_moonrise = [None] * nDays
        self.jd_moonset = [None] * nDays
        self.solar_month = [None] * nDays
        self.solar_month_end_time = [None] * nDays
        self.solar_month_day = [None] * nDays
        self.tropical_month = [None] * nDays
        self.tropical_month_end_time = [None] * nDays

        solar_month_sunrise = [None] * nDays

        self.lunar_month = [None] * nDays
        self.tithi_data = [None] * nDays
        self.tithi_sunrise = [None] * nDays
        self.nakshatram_data = [None] * nDays
        self.nakshatram_sunrise = [None] * nDays
        self.yoga_data = [None] * nDays
        self.yoga_sunrise = [None] * nDays
        self.karanam_data = [None] * nDays
        self.rashi_data = [None] * nDays
        self.kaalas = [None] * nDays

        if compute_lagnams:
            self.lagna_data = [None] * nDays

        self.weekday = [None] * nDays
        daily_panchaangas: List[daily.DailyPanchanga] = [None] * nDays

        # Computing solar month details for Dec 31
        # rather than Jan 1, since we have an always increment
        # solar_month_day at the start of the loop across every day in
        # year
        [prev_day_yy, prev_day_mm, prev_day_dd] = temporal.jd_to_utc_gregorian(self.jd_start_utc - 1)[:3]
        daily_panchangam_start = daily.DailyPanchanga(city=self.city, year=prev_day_yy, month=prev_day_mm, day=prev_day_dd, ayanamsha_id=self.ayanamsha_id)
        daily_panchangam_start.compute_solar_day()
        self.solar_month[1] = daily_panchangam_start.solar_month
        solar_month_day = daily_panchangam_start.solar_month_day

        solar_month_today_sunset = temporal.get_angam(daily_panchangam_start.jd_sunset, temporal.SOLAR_MONTH, ayanamsha_id=self.ayanamsha_id)
        solar_month_tmrw_sunrise = temporal.get_angam(daily_panchangam_start.jd_sunrise + 1, temporal.SOLAR_MONTH, ayanamsha_id=self.ayanamsha_id)
        month_start_after_sunset = solar_month_today_sunset != solar_month_tmrw_sunrise

        #############################################################
        # Compute all parameters -- sun/moon latitude/longitude etc #
        #############################################################

        for d in range(nDays):
            self.weekday[d] = (self.weekday_start + d - 1) % 7

        for d in range(-1, nDays - 1):
            # TODO: Eventually, we are shifting to an array of daily panchangas. Reason: Better modularity.
            # The below block is temporary code to make the transition seamless.
            (year_d, month_d, day_d, _) = temporal.jd_to_utc_gregorian(self.jd_start_utc + d)
            daily_panchaangas[d + 1] = daily.DailyPanchanga(city=self.city, year=year_d, month=month_d, day=day_d, ayanamsha_id=self.ayanamsha_id, previous_day_panchangam=daily_panchaangas[d])
            daily_panchaangas[d + 1].compute_sun_moon_transitions(previous_day_panchangam=daily_panchaangas[d])
            daily_panchaangas[d + 1].compute_solar_month()
            self.jd_midnight[d + 1] = daily_panchaangas[d + 1].julian_day_start
            self.jd_sunrise[d + 1] = daily_panchaangas[d + 1].jd_sunrise
            self.jd_sunset[d + 1] = daily_panchaangas[d + 1].jd_sunset
            self.jd_moonrise[d + 1] = daily_panchaangas[d + 1].jd_moonrise
            self.jd_moonset[d + 1] = daily_panchaangas[d + 1].jd_moonset
            self.solar_month[d + 1] = daily_panchaangas[d + 1].solar_month_sunset

            solar_month_sunrise[d + 1] = daily_panchaangas[d + 1].solar_month_sunrise

            if (d <= 0):
                continue
                # This is just to initialise, since for a lot of calculations,
                # we require comparing with tomorrow's data. This computes the
                # data for day 0, -1.

            # Solar month calculations
            if month_start_after_sunset is True:
                solar_month_day = 0
                month_start_after_sunset = False

            solar_month_end_jd = None
            if self.solar_month[d] != self.solar_month[d + 1]:
                solar_month_day = solar_month_day + 1
                if self.solar_month[d] != solar_month_sunrise[d + 1]:
                    month_start_after_sunset = True
                    [_m, solar_month_end_jd] = temporal.get_angam_data(
                        self.jd_sunrise[d], self.jd_sunrise[d + 1], temporal.SOLAR_MONTH,
                        ayanamsha_id=self.ayanamsha_id)[0]
            elif solar_month_sunrise[d] != self.solar_month[d]:
                # sankrAnti!
                # sun moves into next rAshi before sunset
                solar_month_day = 1
                [_m, solar_month_end_jd] = temporal.get_angam_data(
                    self.jd_sunrise[d], self.jd_sunrise[d + 1], temporal.SOLAR_MONTH,
                    ayanamsha_id=self.ayanamsha_id)[0]
            else:
                solar_month_day = solar_month_day + 1
                solar_month_end_jd = None

            self.solar_month_end_time[d] = solar_month_end_jd

            self.solar_month_day[d] = solar_month_day

            # Compute all the anga datas
            self.tithi_data[d] = daily_panchaangas[d].tithi_data
            self.tithi_sunrise[d] = daily_panchaangas[d].tithi_at_sunrise
            self.nakshatram_data[d] = daily_panchaangas[d].nakshatram_data
            self.nakshatram_sunrise[d] = daily_panchaangas[d].nakshatram_at_sunrise
            self.yoga_data[d] = daily_panchaangas[d].yoga_data
            self.yoga_sunrise[d] = daily_panchaangas[d].yoga_at_sunrise
            self.karanam_data[d] = daily_panchaangas[d].karanam_data
            self.rashi_data[d] = daily_panchaangas[d].rashi_data
            self.kaalas[d] = daily_panchaangas[d].get_kaalas()
            if compute_lagnams:
                self.lagna_data[d] = daily_panchaangas[d].get_lagna_data()

    def assignLunarMonths(self):
        last_d_assigned = 0
        last_new_moon_start, last_new_moon_end = temporal.get_angam_span(
            self.jd_start_utc - self.tithi_sunrise[1] - 3, self.jd_start_utc - self.tithi_sunrise[1] + 3, temporal.TITHI, 30, ayanamsha_id=self.ayanamsha_id)
        this_new_moon_start, this_new_moon_end = temporal.get_angam_span(last_new_moon_start + 24, last_new_moon_start + 32, temporal.TITHI, 30, ayanamsha_id=self.ayanamsha_id)
        # Check if current mAsa is adhika here
        isAdhika = temporal.get_solar_rashi(last_new_moon_end, ayanamsha_id=self.ayanamsha_id) ==\
            temporal.get_solar_rashi(this_new_moon_end, ayanamsha_id=self.ayanamsha_id)

        while last_new_moon_start < self.jd_start_utc + self.duration + 1:
            next_new_moon_start, next_new_moon_end = temporal.get_angam_span(this_new_moon_start + 24, this_new_moon_start + 32, temporal.TITHI, 30, ayanamsha_id=self.ayanamsha_id)
            for i in range(last_d_assigned + 1, last_d_assigned + 32):
                last_solar_month = temporal.get_solar_rashi(this_new_moon_end, ayanamsha_id=self.ayanamsha_id)

                if i > self.duration + 1 or self.jd_sunrise[i] > this_new_moon_end:
                    last_d_assigned = i - 1
                    break
                if isAdhika:
                    self.lunar_month[i] = (last_solar_month % 12) + .5
                else:
                    self.lunar_month[i] = last_solar_month

            isAdhika = temporal.get_solar_rashi(this_new_moon_end, ayanamsha_id=self.ayanamsha_id) ==\
                temporal.get_solar_rashi(next_new_moon_end, ayanamsha_id=self.ayanamsha_id)
            last_new_moon_start = this_new_moon_start
            last_new_moon_end = this_new_moon_end
            this_new_moon_start = next_new_moon_start
            this_new_moon_end = next_new_moon_end

    def get_angams_for_kaalas(self, d, get_angam_func, kaala_type):
        jd_sunrise = self.jd_sunrise[d]
        jd_sunrise_tmrw = self.jd_sunrise[d + 1]
        jd_sunrise_datmrw = self.jd_sunrise[d + 2]
        jd_sunset = self.jd_sunset[d]
        jd_sunset_tmrw = self.jd_sunset[d + 1]
        jd_moonrise = self.jd_moonrise[d]
        jd_moonrise_tmrw = self.jd_moonrise[d + 1]
        if kaala_type == 'sunrise':
            angams = [get_angam_func(jd_sunrise, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunrise, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunrise_tmrw, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunrise_tmrw, ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'sunset':
            angams = [get_angam_func(jd_sunset, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunset, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunset_tmrw, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunset_tmrw, ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'praatah':
            angams = [get_angam_func(jd_sunrise, ayanamsha_id=self.ayanamsha_id),  # praatah1 start
                      # praatah1 end
                      get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (1.0 / 5.0),
                                     ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunrise_tmrw, ayanamsha_id=self.ayanamsha_id),  # praatah2 start
                      # praatah2 end
                      get_angam_func(jd_sunrise_tmrw + \
                                     (jd_sunset_tmrw - jd_sunrise_tmrw) * (1.0 / 5.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'sangava':
            angams = [
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (1.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (2.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw +
                               (jd_sunset_tmrw - jd_sunrise_tmrw) * (1.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw +
                               (jd_sunset_tmrw - jd_sunrise_tmrw) * (2.0 / 5.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'madhyaahna':
            angams = [
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (2.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (3.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw +
                               (jd_sunset_tmrw - jd_sunrise_tmrw) * (2.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw + (jd_sunset_tmrw -
                                                  jd_sunrise_tmrw) * (3.0 / 5.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'aparaahna':
            angams = [
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (3.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (4.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw +
                               (jd_sunset_tmrw - jd_sunrise_tmrw) * (3.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw +
                               (jd_sunset_tmrw - jd_sunrise_tmrw) * (4.0 / 5.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'saayaahna':
            angams = [
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (4.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (5.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw +
                               (jd_sunset_tmrw - jd_sunrise_tmrw) * (4.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw +
                               (jd_sunset_tmrw - jd_sunrise_tmrw) * (5.0 / 5.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'madhyaraatri':
            angams = [
                get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (2.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (3.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset_tmrw +
                               (jd_sunrise_datmrw - jd_sunset_tmrw) * (2.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset_tmrw +
                               (jd_sunrise_datmrw - jd_sunset_tmrw) * (3.0 / 5.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'pradosha':
            # pradOSo.astamayAdUrdhvaM ghaTikAdvayamiShyatE (tithyAdi tattvam, Vrat Parichay p. 25 Gita Press)
            angams = [get_angam_func(jd_sunset, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (1.0 / 15.0),
                                     ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunset_tmrw, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_sunset_tmrw +
                                     (jd_sunrise_datmrw - jd_sunset_tmrw) * (1.0 / 15.0),
                                     ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'nishita':
            angams = [
                get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (7.0 / 15.0),
                               ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (8.0 / 15.0),
                               ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset_tmrw +
                               (jd_sunrise_datmrw - jd_sunset_tmrw) * (7.0 / 15.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset_tmrw +
                               (jd_sunrise_datmrw - jd_sunset_tmrw) * (8.0 / 15.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'dinamaana':
            angams = [
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (0.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise + (jd_sunset - jd_sunrise) * (5.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw +
                               (jd_sunset_tmrw - jd_sunrise_tmrw) * (0.0 / 5.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunrise_tmrw + (jd_sunset_tmrw -
                                                  jd_sunrise_tmrw) * (5.0 / 5.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'raatrimaana':
            angams = [
                get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (0.0 / 15.0),
                               ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (15.0 / 15.0),
                               ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset_tmrw +
                               (jd_sunrise_datmrw - jd_sunset_tmrw) * (0.0 / 15.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset_tmrw +
                               (jd_sunrise_datmrw - jd_sunset_tmrw) * (15.0 / 15.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'arunodaya':  # deliberately not simplifying expressions involving 15/15
            angams = [
                get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (13.0 / 15.0),
                               ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset + (jd_sunrise_tmrw - jd_sunset) * (15.0 / 15.0),
                               ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset_tmrw +
                               (jd_sunrise_datmrw - jd_sunset_tmrw) * (13.0 / 15.0), ayanamsha_id=self.ayanamsha_id),
                get_angam_func(jd_sunset_tmrw +
                               (jd_sunrise_datmrw - jd_sunset_tmrw) * (15.0 / 15.0), ayanamsha_id=self.ayanamsha_id)]
        elif kaala_type == 'moonrise':
            angams = [get_angam_func(jd_moonrise, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_moonrise, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_moonrise_tmrw, ayanamsha_id=self.ayanamsha_id),
                      get_angam_func(jd_moonrise_tmrw, ayanamsha_id=self.ayanamsha_id)]
        else:
            # Error!
            raise ValueError('Unkown kaala "%s" input!' % kaala_type)
        return angams

    def add_festival(self, festival_name, d, debug=False):
        if debug:
            logging.debug('%03d: %s ' % (d, festival_name))
        if festival_name in self.fest_days:
            if d not in self.fest_days[festival_name]:
                # Second occurrence of a festival within a
                # Gregorian calendar year
                if (d - 1) in self.fest_days[festival_name]:
                    # No festival occurs on consecutive days; paraviddha assigned twice
                    logging.warning('%s occurring on two consecutive days (%d, %d). Removing! paraviddha assigned twice?' % (festival_name, d - 1, d))
                    self.fest_days[festival_name].remove(d - 1)
                self.fest_days[festival_name].append(d)
        else:
            self.fest_days[festival_name] = [d]

    def assign_chandra_darshanam(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)
            # Chandra Darshanam
            if self.tithi_sunrise[d] == 1 or self.tithi_sunrise[d] == 2:
                tithi_sunset = temporal.get_tithi(self.jd_sunset[d], ayanamsha_id=self.ayanamsha_id)
                tithi_sunset_tmrw = temporal.get_tithi(self.jd_sunset[d + 1],
                                                       ayanamsha_id=self.ayanamsha_id)
                # if tithi_sunset <= 2 and tithi_sunset_tmrw != 2:
                if tithi_sunset <= 2:
                    if tithi_sunset == 1:
                        self.festivals[d + 1].append('candra-darzanam')
                    else:
                        self.festivals[d].append('candra-darzanam')
                elif tithi_sunset_tmrw == 2:
                    self.festivals[d + 1].append('candra-darzanam')

    def assign_chaturthi_vratam(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # SANKATAHARA chaturthi
            if self.tithi_sunrise[d] == 18 or self.tithi_sunrise[d] == 19:
                ldiff_moonrise_yest = (swe.calc_ut(self.jd_moonrise[d - 1], swe.MOON)[0][0] - swe.calc_ut(self.jd_moonrise[d - 1], swe.SUN)[0][0]) % 360
                ldiff_moonrise = (swe.calc_ut(self.jd_moonrise[d], swe.MOON)[0][0] - swe.calc_ut(self.jd_moonrise[d], swe.SUN)[0][0]) % 360
                ldiff_moonrise_tmrw = (swe.calc_ut(self.jd_moonrise[d + 1], swe.MOON)[0][0] - swe.calc_ut(self.jd_moonrise[d + 1], swe.SUN)[0][0]) % 360
                tithi_moonrise_yest = int(1 + floor(ldiff_moonrise_yest / 12.0))
                tithi_moonrise = int(1 + floor(ldiff_moonrise / 12.0))
                tithi_moonrise_tmrw = int(1 + floor(ldiff_moonrise_tmrw / 12.0))

                _m = self.lunar_month[d]
                if floor(_m) != _m:
                    _m = 13  # Adhika masa
                chaturthi_name = temporal.NAMES['SANKATAHARA_CHATURTHI_NAMES']['hk'][_m] + '-mahAgaNapati '

                if tithi_moonrise == 19:
                    # otherwise yesterday would have already been assigned
                    if tithi_moonrise_yest != 19:
                        chaturthi_name = '%s%s' % ('aGgArakI~' if self.weekday[d] == 2 else '', chaturthi_name)
                        self.festivals[d].append(chaturthi_name + 'saGkaTahara-caturthI-vratam')
                        # shravana krishna chaturthi
                        if self.lunar_month[d] == 5:
                            chaturthi_name = '%s%s' % ('aGgArakI~' if self.weekday[d] == 2 else '', chaturthi_name)
                            self.festivals[d][-1] = chaturthi_name + 'mahAsaGkaTahara-caturthI-vratam'
                elif tithi_moonrise_tmrw == 19:
                    chaturthi_name = '%s%s' % ('aGgArakI~' if self.weekday[d + 1] == 2 else '', chaturthi_name)
                    self.festivals[d + 1].append(chaturthi_name + 'saGkaTahara-caturthI-vratam')
                    # self.lunar_month[d] and[d + 1] are same, so checking [d] is enough
                    if self.lunar_month[d] == 5:
                        chaturthi_name = '%s%s' % ('aGgArakI~' if self.weekday[d] == 2 else '', chaturthi_name)
                        self.festivals[d + 1][-1] = chaturthi_name + 'mahAsaGkaTahara-caturthI-vratam'
                else:
                    if tithi_moonrise_yest != 19:
                        if tithi_moonrise == 18 and tithi_moonrise_tmrw == 20:
                            # No vyApti on either day -- pick parA, i.e. next day.
                            chaturthi_name = '%s%s' % ('aGgArakI~' if self.weekday[d + 1] == 2 else '', chaturthi_name)
                            self.festivals[d + 1].append(chaturthi_name + 'saGkaTahara-caturthI-vratam')
                            # shravana krishna chaturthi
                            if self.lunar_month[d] == 5:
                                chaturthi_name = '%s%s' % ('aGgArakI~' if self.weekday[d + 1] == 2 else '', chaturthi_name)
                                self.festivals[d + 1][-1] = chaturthi_name + 'mahAsaGkaTahara-caturthI-vratam'

    def assign_shasthi_vratam(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)
            # # SHASHTHI Vratam
            # Check only for Adhika maasa here...
            festival_name = 'SaSThI-vratam'
            if self.lunar_month[d] == 8:
                festival_name = 'skanda' + festival_name
            elif self.lunar_month[d] == 4:
                festival_name = 'kumAra-' + festival_name
            elif self.lunar_month[d] == 6:
                festival_name = 'SaSThIdEvI-' + festival_name
            elif self.lunar_month[d] == 9:
                festival_name = 'subrahmaNya-' + festival_name

            if self.tithi_sunrise[d] == 5 or self.tithi_sunrise[d] == 6:
                angams = self.get_angams_for_kaalas(d, temporal.get_tithi, 'madhyaahna')
                if angams[0] == 6 or angams[1] == 6:
                    if festival_name in self.fest_days:
                        # Check if yesterday was assigned already
                        # to this puurvaviddha festival!
                        if self.fest_days[festival_name].count(d - 1) == 0:
                            self.add_festival(festival_name, d, debug_festivals)
                    else:
                        self.add_festival(festival_name, d, debug_festivals)
                elif angams[2] == 6 or angams[3] == 6:
                    self.add_festival(festival_name, d + 1, debug_festivals)
                else:
                    # This means that the correct angam did not
                    # touch the kaala on either day!
                    # sys.stderr.write('Could not assign puurvaviddha day for %s!\
                    # Please check for unusual cases.\n' % festival_name)
                    if angams[2] == 6 + 1 or angams[3] == 6 + 1:
                        # Need to assign a day to the festival here
                        # since the angam did not touch kaala on either day
                        # BUT ONLY IF YESTERDAY WASN'T ALREADY ASSIGNED,
                        # THIS BEING PURVAVIDDHA
                        # Perhaps just need better checking of
                        # conditions instead of this fix
                        if festival_name in self.fest_days:
                            if self.fest_days[festival_name].count(d - 1) == 0:
                                self.add_festival(festival_name, d, debug_festivals)
                        else:
                            self.add_festival(festival_name, d, debug_festivals)

    def assign_vishesha_saptami(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # SPECIAL SAPTAMIs
            if self.weekday[d] == 0 and (self.tithi_sunrise[d] % 15) == 7:
                festival_name = 'bhAnusaptamI'
                if self.tithi_sunrise[d] == 7:
                    festival_name = 'vijayA' + '~' + festival_name
                if self.nakshatram_sunrise[d] == 27:
                    # Even more auspicious!
                    festival_name += '★'
                self.add_festival(festival_name, d, debug_festivals)

            if temporal.get_angam(self.jd_sunrise[d], temporal.NAKSHATRA_PADA,
                                  ayanamsha_id=self.ayanamsha_id) == 49 and \
                    self.tithi_sunrise[d] == 7:
                self.add_festival('bhadrA~saptamI', d, debug_festivals)

            if self.solar_month_end_time[d] is not None:
                # we have a Sankranti!
                if self.tithi_sunrise[d] == 7:
                    self.add_festival('mahAjayA~saptamI', d, debug_festivals)

    def assign_ekadashi_vratam(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # checking @ 6am local - can we do any better?
            local_time = tz(self.city.timezone).localize(datetime(y, m, dt, 6, 0, 0))
            # compute offset from UTC in hours
            tz_off = (datetime.utcoffset(local_time).days * 86400 +
                      datetime.utcoffset(local_time).seconds) / 3600.0

            # EKADASHI Vratam
            # One of two consecutive tithis must appear @ sunrise!

            if (self.tithi_sunrise[d] % 15) == 10 or (self.tithi_sunrise[d] % 15) == 11:
                yati_ekadashi_fday = smaarta_ekadashi_fday = vaishnava_ekadashi_fday = None
                ekadashi_tithi_days = [x % 15 for x in self.tithi_sunrise[d:d + 3]]
                if self.tithi_sunrise[d] > 15:
                    ekadashi_paksha = 'krishna'
                else:
                    ekadashi_paksha = 'shukla'
                if ekadashi_tithi_days in [[11, 11, 12], [10, 12, 12]]:
                    smaarta_ekadashi_fday = d + 1
                    tithi_arunodayam = temporal.get_tithi(self.jd_sunrise[d + 1] - (1 / 15.0) * (self.jd_sunrise[d + 1] - self.jd_sunrise[d]), ayanamsha_id=self.ayanamsha_id)
                    if tithi_arunodayam % 15 == 10:
                        vaishnava_ekadashi_fday = d + 2
                    else:
                        vaishnava_ekadashi_fday = d + 1
                elif ekadashi_tithi_days in [[10, 12, 13], [11, 12, 13], [11, 12, 12], [11, 12, 14]]:
                    smaarta_ekadashi_fday = d
                    tithi_arunodayam = temporal.get_tithi(self.jd_sunrise[d] - (1 / 15.0) * (self.jd_sunrise[d] - self.jd_sunrise[d - 1]), ayanamsha_id=self.ayanamsha_id)
                    if tithi_arunodayam % 15 == 11 and ekadashi_tithi_days in [[11, 12, 13], [11, 12, 14]]:
                        vaishnava_ekadashi_fday = d
                    else:
                        vaishnava_ekadashi_fday = d + 1
                elif ekadashi_tithi_days in [[10, 11, 13], [11, 11, 13]]:
                    smaarta_ekadashi_fday = d
                    vaishnava_ekadashi_fday = d + 1
                    yati_ekadashi_fday = d + 1
                else:
                    pass
                    # These combinations are taken care of, either in the past or future.
                    # if ekadashi_tithi_days == [10, 11, 12]:
                    #     logging.debug('Not assigning. Maybe tomorrow?')
                    # else:
                    #     logging.debug(('!!', d, ekadashi_tithi_days))

                if yati_ekadashi_fday == smaarta_ekadashi_fday == vaishnava_ekadashi_fday is None:
                    # Must have already assigned
                    pass
                elif yati_ekadashi_fday is None:
                    if smaarta_ekadashi_fday == vaishnava_ekadashi_fday:
                        # It's sarva ekadashi
                        self.add_festival('sarva-' + temporal.get_ekadashi_name(ekadashi_paksha, self.lunar_month[d]), smaarta_ekadashi_fday, debug_festivals)
                        if ekadashi_paksha == 'shukla':
                            if self.solar_month[d] == 9:
                                self.add_festival('sarva-vaikuNTha-EkAdazI', smaarta_ekadashi_fday, debug_festivals)
                    else:
                        self.add_festival('smArta-' + temporal.get_ekadashi_name(ekadashi_paksha, self.lunar_month[d]), smaarta_ekadashi_fday, debug_festivals)
                        self.add_festival('vaiSNava-' + temporal.get_ekadashi_name(ekadashi_paksha, self.lunar_month[d]), vaishnava_ekadashi_fday, debug_festivals)
                        if ekadashi_paksha == 'shukla':
                            if self.solar_month[d] == 9:
                                self.add_festival('smArta-vaikuNTha-EkAdazI', smaarta_ekadashi_fday, debug_festivals)
                                self.add_festival('vaiSNava-vaikuNTha-EkAdazI', vaishnava_ekadashi_fday, debug_festivals)
                else:
                    self.add_festival('smArta-' + temporal.get_ekadashi_name(ekadashi_paksha, self.lunar_month[d]) + ' (gRhastha)', smaarta_ekadashi_fday, debug_festivals)
                    self.add_festival('smArta-' + temporal.get_ekadashi_name(ekadashi_paksha, self.lunar_month[d]) + ' (sannyastha)', yati_ekadashi_fday, debug_festivals)
                    self.add_festival('vaiSNava-' + temporal.get_ekadashi_name(ekadashi_paksha, self.lunar_month[d]), vaishnava_ekadashi_fday, debug_festivals)
                    if self.solar_month[d] == 9:
                        if ekadashi_paksha == 'shukla':
                            self.add_festival('smArta-vaikuNTha-EkAdazI (gRhastha)', smaarta_ekadashi_fday, debug_festivals)
                            self.add_festival('smArta-vaikuNTha-EkAdazI (sannyastha)', yati_ekadashi_fday, debug_festivals)
                            self.add_festival('vaiSNava-vaikuNTha-EkAdazI', vaishnava_ekadashi_fday, debug_festivals)

                if yati_ekadashi_fday == smaarta_ekadashi_fday == vaishnava_ekadashi_fday is None:
                    # Must have already assigned
                    pass
                else:
                    if self.solar_month[d] == 8 and ekadashi_paksha == 'shukla':
                            # self.add_festival('guruvAyupura-EkAdazI', smaarta_ekadashi_fday, debug_festivals)
                            self.add_festival('guruvAyupura-EkAdazI', vaishnava_ekadashi_fday, debug_festivals)
                            self.add_festival('kaizika-EkAdazI', vaishnava_ekadashi_fday, debug_festivals)

                    # Harivasara Computation
                    if ekadashi_paksha == 'shukla':
                        harivasara_end = brentq(temporal.get_angam_float, self.jd_sunrise[smaarta_ekadashi_fday] - 2, self.jd_sunrise[smaarta_ekadashi_fday] + 2, args=(temporal.TITHI_PADA, -45, self.ayanamsha_id, False))
                    else:
                        harivasara_end = brentq(temporal.get_angam_float, self.jd_sunrise[smaarta_ekadashi_fday] - 2, self.jd_sunrise[smaarta_ekadashi_fday] + 2, args=(temporal.TITHI_PADA, -105, self.ayanamsha_id, False))
                    [_y, _m, _d, _t] = temporal.jd_to_utc_gregorian(harivasara_end + (tz_off / 24.0))
                    hariv_end_time = jyotisha.panchangam.temporal.hour.Hour(temporal.jd_to_utc_gregorian(harivasara_end + (tz_off / 24.0))[3]).toString(format=self.fmt)
                    fday_hv = temporal.utc_gregorian_to_jd(_y, _m, _d, 0) - self.jd_start_utc + 1
                    self.festivals[int(fday_hv)].append('harivAsaraH\\textsf{%s}{\\RIGHTarrow}\\textsf{%s}' % ('', hariv_end_time))

    def assign_mahadwadashi(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)
            # 8 MAHA DWADASHIS
            if (self.tithi_sunrise[d] % 15) == 11 and (self.tithi_sunrise[d + 1] % 15) == 11:
                self.add_festival('unmIlanI~mahAdvAdazI', d + 1, debug_festivals)

            if (self.tithi_sunrise[d] % 15) == 12 and (self.tithi_sunrise[d + 1] % 15) == 12:
                self.add_festival('vyaJjulI~mahAdvAdazI', d, debug_festivals)

            if (self.tithi_sunrise[d] % 15) == 11 and (self.tithi_sunrise[d + 1] % 15) == 13:
                self.add_festival('trisparzA~mahAdvAdazI', d, debug_festivals)

            if (self.tithi_sunrise[d] % 15) == 0 and (self.tithi_sunrise[d + 1] % 15) == 0:
                # Might miss out on those parva days right after Dec 31!
                if (d - 3) > 0:
                    self.add_festival('pakSavardhinI~mahAdvAdazI', d - 3, debug_festivals)

            if self.nakshatram_sunrise[d] == 4 and (self.tithi_sunrise[d] % 15) == 12:
                self.add_festival('pApanAzinI~mahAdvAdazI', d, debug_festivals)

            if self.nakshatram_sunrise[d] == 7 and (self.tithi_sunrise[d] % 15) == 12:
                self.add_festival('jayantI~mahAdvAdazI', d, debug_festivals)

            if self.nakshatram_sunrise[d] == 8 and (self.tithi_sunrise[d] % 15) == 12:
                self.add_festival('jayA~mahAdvAdazI', d, debug_festivals)

            if self.nakshatram_sunrise[d] == 8 and (self.tithi_sunrise[d] % 15) == 12 and self.lunar_month[d] == 12:
                # Better checking needed (for other than sunrise).
                # Last occurred on 27-02-1961 - pushya nakshatra and phalguna krishna dvadashi (or shukla!?)
                self.add_festival('gOvinda~mahAdvAdazI', d, debug_festivals)

            if (self.tithi_sunrise[d] % 15) == 12:
                if self.nakshatram_sunrise[d] in [21, 22, 23]:
                    # We have a dwadashi near shravana, check for Shravana sparsha
                    for td in self.tithi_data[d:d + 2]:
                        (t12, t12_end) = td[0]
                        if t12_end is None:
                            continue
                        if (t12 % 15) == 11:
                            if temporal.get_angam(t12_end, temporal.NAKSHATRAM, ayanamsha_id=self.ayanamsha_id) == 22:
                                if (self.tithi_sunrise[d] % 15) == 12 and (self.tithi_sunrise[d + 1] % 15) == 12:
                                    self.add_festival('vijayA/zravaNa-mahAdvAdazI', d, debug_festivals)
                                elif (self.tithi_sunrise[d] % 15) == 12:
                                    self.add_festival('vijayA/zravaNa-mahAdvAdazI', d, debug_festivals)
                                elif (self.tithi_sunrise[d + 1] % 15) == 12:
                                    self.add_festival('vijayA/zravaNa-mahAdvAdazI', d + 1, debug_festivals)
                        if (t12 % 15) == 12:
                            if temporal.get_angam(t12_end, temporal.NAKSHATRAM, ayanamsha_id=self.ayanamsha_id) == 22:
                                if (self.tithi_sunrise[d] % 15) == 12 and (self.tithi_sunrise[d + 1] % 15) == 12:
                                    self.add_festival('vijayA/zravaNa-mahAdvAdazI', d, debug_festivals)
                                elif (self.tithi_sunrise[d] % 15) == 12:
                                    self.add_festival('vijayA/zravaNa-mahAdvAdazI', d, debug_festivals)
                                elif (self.tithi_sunrise[d + 1] % 15) == 12:
                                    self.add_festival('vijayA/zravaNa-mahAdvAdazI', d + 1, debug_festivals)

            if self.nakshatram_sunrise[d] == 22 and (self.tithi_sunrise[d] % 15) == 12:
                self.add_festival('vijayA/zravaNa-mahAdvAdazI', d, debug_festivals)

    def assign_pradosha_vratam(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)
            # compute offset from UTC in hours
            # PRADOSHA Vratam
            pref = ''
            if self.tithi_sunrise[d] in (12, 13, 27, 28):
                tithi_sunset = temporal.get_tithi(self.jd_sunset[d], ayanamsha_id=self.ayanamsha_id) % 15
                tithi_sunset_tmrw = temporal.get_tithi(self.jd_sunset[d + 1],
                                                       ayanamsha_id=self.ayanamsha_id) % 15
                if tithi_sunset <= 13 and tithi_sunset_tmrw != 13:
                    fday = d
                elif tithi_sunset_tmrw == 13:
                    fday = d + 1
                if self.weekday[fday] == 1:
                    pref = 'sOma-'
                elif self.weekday[fday] == 6:
                    pref = 'zani-'
                self.add_festival(pref + 'pradOSa-vratam', fday, debug_festivals)

    def assign_vishesha_trayodashi(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)
            # VARUNI TRAYODASHI
            if self.lunar_month[d] == 12 and self.tithi_sunrise[d] == 28:
                if temporal.get_angam(self.jd_sunrise[d], temporal.NAKSHATRAM,
                                      ayanamsha_id=self.ayanamsha_id) == 24:
                    vtr_name = 'vAruNI~trayOdazI'
                    if self.weekday[d] == 6:
                        vtr_name = 'mahA' + vtr_name
                        if temporal.get_angam(self.jd_sunrise[d],
                                              temporal.YOGA,
                                              ayanamsha_id=self.ayanamsha_id) == 23:
                            vtr_name = 'mahA' + vtr_name
                    self.add_festival(vtr_name, d, debug_festivals)

    def assign_amavasya_yoga(self, debug_festivals=False):
        if 'amAvAsyA' not in self.fest_days:
            logging.error('Must compute amAvAsyA before coming here!')
        else:
            ama_days = self.fest_days['amAvAsyA']
            for d in ama_days:
                # Get Name
                if self.lunar_month[d] == 6:
                    pref = '(%s) mahAlaya ' % (temporal.get_chandra_masa(self.lunar_month[d], temporal.NAMES, 'hk', visarga=False))
                elif self.solar_month[d] == 4:
                    pref = '%s (kaTaka) ' % (temporal.get_chandra_masa(self.lunar_month[d], temporal.NAMES, 'hk', visarga=False))
                elif self.solar_month[d] == 10:
                    pref = 'mauni (%s/makara) ' % (temporal.get_chandra_masa(self.lunar_month[d], temporal.NAMES, 'hk', visarga=False))
                else:
                    pref = temporal.get_chandra_masa(self.lunar_month[d], temporal.NAMES, 'hk', visarga=False) + '-'

                ama_nakshatram_today = self.get_angams_for_kaalas(d, temporal.get_nakshatram, 'aparaahna')[:2]
                suff = ''
                # Assign
                if 23 in ama_nakshatram_today and self.lunar_month[d] == 10:
                    suff = ' (alabhyam–zraviSThA)'
                elif 24 in ama_nakshatram_today and self.lunar_month[d] == 10:
                    suff = ' (alabhyam–zatabhiSak)'
                elif ama_nakshatram_today[0] in [15, 16, 17, 6, 7, 8, 23, 24, 25]:
                    suff = ' (alabhyam–%s)' % jyotisha.panchangam.temporal.NAMES['NAKSHATRAM_NAMES']['hk'][ama_nakshatram_today[0]]
                elif ama_nakshatram_today[1] in [15, 16, 17, 6, 7, 8, 23, 24, 25]:
                    suff = ' (alabhyam–%s)' % jyotisha.panchangam.temporal.NAMES['NAKSHATRAM_NAMES']['hk'][ama_nakshatram_today[1]]
                if self.weekday[d] in [1, 2, 4]:
                    if suff == '':
                        suff = ' (alabhyam–puSkalA)'
                    else:
                        suff = suff.replace(')', ', puSkalA)')
                self.add_festival(pref + 'amAvAsyA' + suff, d, debug_festivals)
        if 'amAvAsyA' in self.fest_days:
            del self.fest_days['amAvAsyA']

        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # SOMAMAVASYA
            if self.tithi_sunrise[d] == 30 and self.weekday[d] == 1:
                self.add_festival('sOmavatI amAvAsyA', d, debug_festivals)

            # AMA-VYATIPATA YOGAH
            # श्रवणाश्विधनिष्ठार्द्रानागदैवतमापतेत् ।
            # रविवारयुतामायां व्यतीपातः स उच्यते ॥
            # व्यतीपाताख्ययोगोऽयं शतार्कग्रहसन्निभः ॥
            # “In Mahabharata, if on a Sunday, Amavasya and one of the stars –
            # Sravanam, Asvini, Avittam, Tiruvadirai or Ayilyam, occurs, then it is called ‘Vyatipatam’.
            # This Vyatipata yoga is equal to a hundred Surya grahanas in merit.”
            tithi_sunset = temporal.get_angam(self.jd_sunset[d], temporal.TITHI, ayanamsha_id=self.ayanamsha_id)
            if self.weekday[d] == 0 and (self.tithi_sunrise[d] == 30 or tithi_sunset == 30):
                # AMAVASYA on a Sunday
                if (self.nakshatram_sunrise[d] in [1, 6, 9, 22, 23] and self.tithi_sunrise[d] == 30) or\
                   (tithi_sunset == 30 and temporal.get_angam(self.jd_sunset[d], temporal.NAKSHATRAM, ayanamsha_id=self.ayanamsha_id) in [1, 6, 9, 22, 23]):
                    festival_name = 'vyatIpAta-yOgaH (alabhyam)'
                    self.add_festival(festival_name, d, debug_festivals)
                    logging.debug('* %d-%02d-%02d> %s!' % (y, m, dt, festival_name))

    def assign_gajachhaya_yoga(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # checking @ 6am local - can we do any better?
            local_time = tz(self.city.timezone).localize(datetime(y, m, dt, 6, 0, 0))
            # compute offset from UTC in hours
            tz_off = (datetime.utcoffset(local_time).days * 86400 +
                      datetime.utcoffset(local_time).seconds) / 3600.0
            # GAJACHHAYA YOGA
            if self.solar_month[d] == 6 and self.solar_month_day[d] == 1:
                moon_magha_jd_start = moon_magha_jd_start = t28_start = None
                moon_magha_jd_end = moon_magha_jd_end = t28_end = None
                moon_hasta_jd_start = moon_hasta_jd_start = t30_start = None
                moon_hasta_jd_end = moon_hasta_jd_end = t30_end = None

                sun_hasta_jd_start, sun_hasta_jd_end = temporal.get_angam_span(
                    self.jd_sunrise[d], self.jd_sunrise[d] + 30, temporal.SOLAR_NAKSH, 13,
                    ayanamsha_id=self.ayanamsha_id)

                moon_magha_jd_start, moon_magha_jd_end = temporal.get_angam_span(
                    sun_hasta_jd_start - 2, sun_hasta_jd_end + 2, temporal.NAKSHATRAM, 10,
                    ayanamsha_id=self.ayanamsha_id)
                if all([moon_magha_jd_start, moon_magha_jd_end]):
                    t28_start, t28_end = temporal.get_angam_span(
                        moon_magha_jd_start - 3, moon_magha_jd_end + 3, temporal.TITHI, 28,
                        ayanamsha_id=self.ayanamsha_id)

                moon_hasta_jd_start, moon_hasta_jd_end = temporal.get_angam_span(
                    sun_hasta_jd_start - 1, sun_hasta_jd_end + 1, temporal.NAKSHATRAM, 13,
                    ayanamsha_id=self.ayanamsha_id)
                if all([moon_hasta_jd_start, moon_hasta_jd_end]):
                    t30_start, t30_end = temporal.get_angam_span(
                        sun_hasta_jd_start - 1, sun_hasta_jd_end + 1, temporal.TITHI, 30,
                        ayanamsha_id=self.ayanamsha_id)

                gc_28 = gc_30 = False

                if all([sun_hasta_jd_start, moon_magha_jd_start, t28_start]):
                    # We have a GC yoga
                    gc_28_start = max(sun_hasta_jd_start, moon_magha_jd_start, t28_start)
                    gc_28_end = min(sun_hasta_jd_end, moon_magha_jd_end, t28_end)

                    if gc_28_start < gc_28_end:
                        gc_28 = True

                if all([sun_hasta_jd_start, moon_hasta_jd_start, t30_start]):
                    # We have a GC yoga
                    gc_30_start = max(sun_hasta_jd_start, moon_hasta_jd_start, t30_start)
                    gc_30_end = min(sun_hasta_jd_end, moon_hasta_jd_end, t30_end)

                    if gc_30_start < gc_30_end:
                        gc_30 = True

            if self.solar_month[d] == 6 and (gc_28 or gc_30):
                if gc_28:
                    gc_28_start += tz_off / 24.0
                    gc_28_end += tz_off / 24.0
                    # sys.stderr.write('28: (%f, %f)\n' % (gc_28_start, gc_28_end))
                    gc_28_d = 1 + floor(gc_28_start - self.jd_start_utc)
                    t1 = jyotisha.panchangam.temporal.hour.Hour(temporal.jd_to_utc_gregorian(gc_28_start)[3]).toString(format=self.fmt)

                    if floor(gc_28_end - 0.5) != floor(gc_28_start - 0.5):
                        # -0.5 is for the fact that julday is zero at noon always, not midnight!
                        offset = 24
                    else:
                        offset = 0
                    t2 = jyotisha.panchangam.temporal.hour.Hour(temporal.jd_to_utc_gregorian(gc_28_end)[3] + offset).toString(format=self.fmt)
                    # sys.stderr.write('gajacchhaya %d\n' % gc_28_d)

                    self.fest_days['gajacchAyA-yOgaH' +
                                   '-\\textsf{' + t1 + '}{\\RIGHTarrow}\\textsf{' +
                                   t2 + '}'] = [gc_28_d]
                    gc_28 = False
                if gc_30:
                    gc_30_start += tz_off / 24.0
                    gc_30_end += tz_off / 24.0
                    # sys.stderr.write('30: (%f, %f)\n' % (gc_30_start, gc_30_end))
                    gc_30_d = 1 + floor(gc_30_start - self.jd_start_utc)
                    t1 = jyotisha.panchangam.temporal.hour.Hour(temporal.jd_to_utc_gregorian(gc_30_start)[3]).toString(format=self.fmt)

                    if floor(gc_30_end - 0.5) != floor(gc_30_start - 0.5):
                        offset = 24
                    else:
                        offset = 0
                    t2 = jyotisha.panchangam.temporal.hour.Hour(temporal.jd_to_utc_gregorian(gc_30_end)[3] + offset).toString(format=self.fmt)
                    # sys.stderr.write('gajacchhaya %d\n' % gc_30_d)

                    self.fest_days['gajacchAyA-yOgaH' +
                                   '-\\textsf{' + t1 + '}{\\RIGHTarrow}\\textsf{' +
                                   t2 + '}'] = [gc_30_d]
                    gc_30 = False

    def assign_mahodaya_ardhodaya(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # MAHODAYAM
            # Can also refer youtube video https://youtu.be/0DBIwb7iaLE?list=PL_H2LUtMCKPjh63PRk5FA3zdoEhtBjhzj&t=6747
            # 4th pada of vyatipatam, 1st pada of Amavasya, 2nd pada of Shravana, Suryodaya, Bhanuvasara = Ardhodayam
            # 4th pada of vyatipatam, 1st pada of Amavasya, 2nd pada of Shravana, Suryodaya, Somavasara = Mahodayam
            if self.lunar_month[d] in [10, 11] and self.tithi_sunrise[d] == 30 or temporal.get_tithi(self.jd_sunset[d], ayanamsha_id=self.ayanamsha_id) == 30:
                if (temporal.get_angam(self.jd_sunrise[d], temporal.YOGA, ayanamsha_id=self.ayanamsha_id) == 17 or temporal.get_angam(self.jd_sunset[d], temporal.YOGA, ayanamsha_id=self.ayanamsha_id) == 17) and \
                        (temporal.get_angam(self.jd_sunrise[d], temporal.NAKSHATRAM, ayanamsha_id=self.ayanamsha_id) == 22 or temporal.get_angam(self.jd_sunset[d], temporal.NAKSHATRAM, ayanamsha_id=self.ayanamsha_id) == 22):
                    if self.weekday[d] == 1:
                        festival_name = 'mahOdaya-puNyakAlaH'
                        self.add_festival(festival_name, d, debug_festivals)
                        # logging.debug('* %d-%02d-%02d> %s!' % (y, m, dt, festival_name))
                    elif self.weekday[d] == 0:
                        festival_name = 'ardhOdaya-puNyakAlaH'
                        self.add_festival(festival_name, d, debug_festivals)
                        # logging.debug('* %d-%02d-%02d> %s!' % (y, m, dt, festival_name))

    def assign_agni_nakshatram(self, debug_festivals=False):
        agni_jd_start = agni_jd_end = None
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

           # AGNI NAKSHATRAM
            # Arbitrarily checking after Mesha 10! Agni Nakshatram can't start earlier...
            if self.solar_month[d] == 1 and self.solar_month_day[d] == 10:
                agni_jd_start, dummy = temporal.get_angam_span(
                    self.jd_sunrise[d], self.jd_sunrise[d] + 30,
                    temporal.SOLAR_NAKSH_PADA, 7, ayanamsha_id=self.ayanamsha_id)
                dummy, agni_jd_end = temporal.get_angam_span(
                    agni_jd_start, agni_jd_start + 30,
                    temporal.SOLAR_NAKSH_PADA, 13, ayanamsha_id=self.ayanamsha_id)

            if self.solar_month[d] == 1 and self.solar_month_day[d] > 10:
                if agni_jd_start is not None:
                    if self.jd_sunset[d] < agni_jd_start < self.jd_sunset[d + 1]:
                        self.add_festival('agninakSatra-ArambhaH', d + 1, debug_festivals)
            if self.solar_month[d] == 2 and self.solar_month_day[d] > 10:
                if agni_jd_end is not None:
                    if self.jd_sunset[d] < agni_jd_end < self.jd_sunset[d + 1]:
                        self.add_festival('agninakSatra-samApanam', d + 1, debug_festivals)

    def assign_tithi_vara_yoga(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # MANGALA-CHATURTHI
            if self.weekday[d] == 2 and (self.tithi_sunrise[d] % 15) == 4:
                festival_name = 'aGgAraka-caturthI'
                if self.tithi_sunrise[d] == 4:
                    festival_name = 'sukhA' + '~' + festival_name
                self.add_festival(festival_name, d, debug_festivals)

            # KRISHNA ANGARAKA CHATURDASHI
            if self.weekday[d] == 2 and self.tithi_sunrise[d] == 29:
                # Double-check rule. When should the vyApti be?
                self.add_festival('kRSNAGgAraka-caturdazI-puNyakAlaH/yamatarpaNam', d, debug_festivals)

            # BUDHASHTAMI
            if self.weekday[d] == 3 and (self.tithi_sunrise[d] % 15) == 8:
                self.add_festival('budhASTamI', d, debug_festivals)

    def assign_bhriguvara_subrahmanya_vratam(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # BHRGUVARA SUBRAHMANYA VRATAM
            if self.solar_month[d] == 7 and self.weekday[d] == 5:
                festival_name = 'bhRguvAra-subrahmaNya-vratam'
                if festival_name not in self.fest_days:
                    # only the first bhRguvAra of tulA mAsa is considered (skAnda purANam)
                    # https://youtu.be/rgXwyo0L3i8?t=222
                    self.add_festival(festival_name, d, debug_festivals)

    def assign_masa_vara_yoga_vratam(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # KRTTIKA SOMAVASARA
            if self.lunar_month[d] == 8 and self.weekday[d] == 1:
                self.add_festival('kRttikA~sOmavAsaraH', d, debug_festivals)

            # SOLAR MONTH-WEEKDAY FESTIVALS
            for (mwd_fest_m, mwd_fest_wd, mwd_fest_name) in ((5, 0, 'ta:AvaNi~JAyir2r2ukkizhamai'),
                                                             (6, 6, 'ta:puraTTAci~can2ikkizhamai'),
                                                             (8, 0, 'ta:kArttigai~JAyir2r2ukkizhamai'),
                                                             (4, 5, 'ta:ADi~veLLikkizhamai'),
                                                             (10, 5, 'ta:tai~veLLikkizhamai'),
                                                             (11, 2, 'ta:mAci~cevvAy')):
                if self.solar_month[d] == mwd_fest_m and self.weekday[d] == mwd_fest_wd:
                    self.add_festival(mwd_fest_name, d, debug_festivals)

    def assign_nakshatra_vara_yoga_vratam(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # NAKSHATRA-WEEKDAY FESTIVALS
            for (nwd_fest_n, nwd_fest_wd, nwd_fest_name) in ((13, 0, 'Adityahasta-puNyakAlaH'),
                                                             (8, 0, 'ravipuSyayOga-puNyakAlaH'),
                                                             (22, 1, 'sOmazrAvaNI-puNyakAlaH'),
                                                             (5, 1, 'sOmamRgazIrSa-puNyakAlaH'),
                                                             (1, 2, 'bhaumAzvinI-puNyakAlaH'),
                                                             (6, 2, 'bhaumArdrA-puNyakAlaH'),
                                                             (17, 3, 'budhAnurAdhA-puNyakAlaH'),
                                                             (8, 4, 'gurupuSya-puNyakAlaH'),
                                                             (27, 5, 'bhRgurEvatI-puNyakAlaH'),
                                                             (4, 6, 'zanirOhiNI-puNyakAlaH'),
                                                             ):
                n_prev = ((nwd_fest_n - 2) % 27) + 1
                if (self.nakshatram_sunrise[d] == nwd_fest_n or self.nakshatram_sunrise[d] == n_prev) and self.weekday[d] == nwd_fest_wd:
                    # Is it necessarily only at sunrise?
                    angams = self.get_angams_for_kaalas(d, temporal.get_nakshatram, 'dinamaana')
                    if any(x == nwd_fest_n for x in [self.nakshatram_sunrise[d], angams[0], angams[1]]):
                        self.add_festival(nwd_fest_name, d, debug_festivals)

    def assign_ayanam(self, debug_festivals=False):
        last_d_assigned = 0
        for d in range(1, self.duration + 1):

            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # checking @ 6am local - can we do any better?
            local_time = tz(self.city.timezone).localize(datetime(y, m, dt, 6, 0, 0))
            # compute offset from UTC in hours
            tz_off = (datetime.utcoffset(local_time).days * 86400 +
                      datetime.utcoffset(local_time).seconds) / 3600.0

            # TROPICAL AYANAMS
            if self.solar_month_day[d] == 1:
                ayana_jd_start = brentq(zodiac.get_nirayana_sun_lon, self.jd_sunrise[d],
                                        self.jd_sunrise[d] + 15, args=(-30 * self.solar_month[d], False))
                [_y, _m, _d, _t] = temporal.jd_to_utc_gregorian(ayana_jd_start + (tz_off / 24.0))
                # Reduce fday by 1 if ayana time precedes sunrise and change increment _t by 24
                fday_nirayana = int(temporal.utc_gregorian_to_jd(_y, _m, _d, 0) - self.jd_start_utc + 1)
                if fday_nirayana > self.duration:
                    continue
                if ayana_jd_start < self.jd_sunrise[fday_nirayana]:
                    fday_nirayana -= 1
                    _t += 24
                ayana_time = jyotisha.panchangam.temporal.hour.Hour(_t).toString(format=self.fmt)

                self.festivals[fday_nirayana].append('%s\\textsf{%s}{\\RIGHTarrow}\\textsf{%s}' % (
                    temporal.NAMES['RTU_MASA_NAMES'][self.script][self.solar_month[d]], '', ayana_time))
                self.tropical_month_end_time[fday_nirayana] = ayana_jd_start
                for i in range(last_d_assigned + 1, fday_nirayana + 1):
                    self.tropical_month[i] = self.solar_month[d]
                last_d_assigned = fday_nirayana
                if self.solar_month[d] == 3:
                    if self.jd_sunset[fday_nirayana] < ayana_jd_start < self.jd_sunset[fday_nirayana + 1]:
                        self.festivals[fday_nirayana].append('dakSiNAyana-puNyakAlaH')
                    else:
                        self.festivals[fday_nirayana - 1].append('dakSiNAyana-puNyakAlaH')
                if self.solar_month[d] == 9:
                    if self.jd_sunset[fday_nirayana] < ayana_jd_start < self.jd_sunset[fday_nirayana + 1]:
                        self.festivals[fday_nirayana + 1].append('uttarAyaNa-puNyakAlaH/mitrOtsavaH')
                    else:
                        self.festivals[fday_nirayana].append('uttarAyaNa-puNyakAlaH/mitrOtsavaH')
        for i in range(last_d_assigned + 1, self.duration + 1):
            self.tropical_month[i] = (self.solar_month[last_d_assigned] % 12) + 1

    def assign_month_day_festivals(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)
            ####################
            # Festival details #
            ####################

            # KARADAIYAN NOMBU
            if self.solar_month[d] == 12 and self.solar_month_day[d] == 1:
                if temporal.get_solar_rashi(self.jd_sunrise[d] - (1 / 15.0) * (self.jd_sunrise[d] - self.jd_sunrise[d - 1])) == 12:
                    # If kumbha prevails two ghatikAs before sunrise, nombu can be done in the early morning itself, else, previous night.
                    self.fest_days['ta:kAraDaiyAn2 nOn2bu'] = [d - 1]
                else:
                    self.fest_days['ta:kAraDaiyAn2 nOn2bu'] = [d]

            # KUCHELA DINAM
            if self.solar_month[d] == 9 and self.solar_month_day[d] <= 7 and self.weekday[d] == 3:
                self.fest_days['kucEla-dinam'] = [d]

            # MESHA SANKRANTI
            if self.solar_month[d] == 1 and self.solar_month[d - 1] == 12:
                # distance from prabhava
                samvatsara_id = (y - 1568) % 60 + 1
                new_yr = 'mESa-saGkrAntiH' + '~(' + temporal.NAMES['SAMVATSARA_NAMES']['hk'][(samvatsara_id % 60) + 1] + \
                         '-' + 'saMvatsaraH' + ')'
                # self.fest_days[new_yr] = [d]
                self.add_festival(new_yr, d, debug_festivals)
                self.add_festival('paJcAGga-paThanam', d, debug_festivals)

    def assign_ayushman_bava_saumya_yoga(self, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            # AYUSHMAN BAVA SAUMYA
            if self.weekday[d] == 3 and temporal.get_angam(self.jd_sunrise[d],
                                                           temporal.YOGA,
                                                           ayanamsha_id=self.ayanamsha_id) == 3:
                if temporal.get_angam(self.jd_sunrise[d], temporal.KARANAM,
                                      ayanamsha_id=self.ayanamsha_id) in list(range(2, 52, 7)):
                    self.add_festival('AyuSmAn-bava-saumya', d, debug_festivals)
            if self.weekday[d] == 3 and temporal.get_angam(self.jd_sunset[d],
                                                           temporal.YOGA,
                                                           ayanamsha_id=self.ayanamsha_id) == 3:
                if temporal.get_angam(self.jd_sunset[d], temporal.KARANAM,
                                      ayanamsha_id=self.ayanamsha_id) in list(range(2, 52, 7)):
                    self.add_festival('AyuSmAn-bava-saumya', d, debug_festivals)

    def assign_festivals_from_rules(self, festival_rules, debug_festivals=False):
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            for festival_name in festival_rules:
                if 'month_type' in festival_rules[festival_name]:
                    month_type = festival_rules[festival_name]['month_type']
                else:
                    # Maybe only description of the festival is given, as computation has been
                    # done in computeFestivals(), without using a rule in festival_rules.json!
                    if 'description_short' in festival_rules[festival_name]:
                        continue
                    raise (ValueError, "No month_type mentioned for %s" % festival_name)
                if 'month_number' in festival_rules[festival_name]:
                    month_num = festival_rules[festival_name]['month_number']
                else:
                    raise (ValueError, "No month_num mentioned for %s" % festival_name)
                if 'angam_type' in festival_rules[festival_name]:
                    angam_type = festival_rules[festival_name]['angam_type']
                else:
                    raise (ValueError, "No angam_type mentioned for %s" % festival_name)
                if 'angam_number' in festival_rules[festival_name]:
                    angam_num = festival_rules[festival_name]['angam_number']
                else:
                    raise (ValueError, "No angam_num mentioned for %s" % festival_name)
                if 'kaala' in festival_rules[festival_name]:
                    kaala = festival_rules[festival_name]['kaala']
                else:
                    kaala = 'sunrise'  # default!
                if 'priority' in festival_rules[festival_name]:
                    priority = festival_rules[festival_name]['priority']
                else:
                    priority = 'puurvaviddha'
                # if 'titles' in festival_rules[festival_name]:
                #     fest_other_names = festival_rules[festival_name]['titles']
                # if 'Nirnaya' in festival_rules[festival_name]:
                #     fest_nirnaya = festival_rules[festival_name]['Nirnaya']
                # if 'references_primary' in festival_rules[festival_name]:
                #     fest_ref1 = festival_rules[festival_name]['references_primary']
                # if 'references_secondary' in festival_rules[festival_name]:
                #     fest_ref2 = festival_rules[festival_name]['references_secondary']
                # if 'comments' in festival_rules[festival_name]:
                #     fest_comments = festival_rules[festival_name]['comments']

                if angam_type == 'tithi' and month_type == 'lunar_month' and angam_num == 1:
                    # Shukla prathama tithis need to be dealt carefully, if e.g. the prathama tithi
                    # does not touch sunrise on either day (the regular check won't work, because
                    # the month itself is different the previous day!)
                    if self.tithi_sunrise[d] == 30 and self.tithi_sunrise[d + 1] == 2 and \
                            self.lunar_month[d + 1] == month_num:
                        # Only in this case, we have a problem
                        self.add_festival(festival_name, d, debug_festivals)
                        continue

                if angam_type == 'day' and month_type == 'solar_month' and self.solar_month[d] == month_num:
                    if self.solar_month_day[d] == angam_num:
                        if kaala == 'arunodaya':
                            angams = self.get_angams_for_kaalas(d - 1, temporal.get_solar_rashi, kaala)
                            if angams[1] == month_num:
                                self.add_festival(festival_name, d, debug_festivals)
                            elif angams[2] == month_num:
                                self.add_festival(festival_name, d + 1, debug_festivals)
                        else:
                            self.add_festival(festival_name, d, debug_festivals)
                elif (month_type == 'lunar_month' and ((self.lunar_month[d] == month_num or month_num == 0) or ((self.lunar_month[d + 1] == month_num and angam_num == 1)))) or \
                        (month_type == 'solar_month' and (self.solar_month[d] == month_num or month_num == 0)):
                    # Using 0 as a special tag to denote every month!
                    if angam_type == 'tithi':
                        angam_sunrise = self.tithi_sunrise
                        angam_data = self.tithi_data
                        get_angam_func = temporal.get_tithi
                        num_angams = 30
                    elif angam_type == 'nakshatram':
                        angam_sunrise = self.nakshatram_sunrise
                        angam_data = self.nakshatram_data
                        get_angam_func = temporal.get_nakshatram
                        num_angams = 27
                    elif angam_type == 'yoga':
                        angam_sunrise = self.yoga_sunrise
                        angam_data = self.yoga_data
                        get_angam_func = temporal.get_yoga
                        num_angams = 27
                    else:
                        raise ValueError('Error; unknown string in rule: "%s"' % (angam_type))

                    if angam_num == 1:
                        prev_angam = num_angams
                    else:
                        prev_angam = angam_num - 1
                    next_angam = (angam_num % num_angams) + 1
                    nnext_angam = (next_angam % 30) + 1

                    fday = None

                    if angam_sunrise[d] == prev_angam or angam_sunrise[d] == angam_num:
                        if kaala == 'arunodaya':
                            # We want for arunodaya *preceding* today's sunrise; therefore, use d - 1
                            angams = self.get_angams_for_kaalas(d - 1, get_angam_func, kaala)
                        else:
                            angams = self.get_angams_for_kaalas(d, get_angam_func, kaala)

                        if angams is None:
                            logging.error('No angams returned! Skipping festival %s' % festival_name)
                            continue
                            # Some error, e.g. weird kaala, so skip festival
                        if debug_festivals:
                            try:
                                logging.debug(('%', festival_name, ': ', festival_rules[festival_name]))
                                logging.debug(("%%angams today & tmrw:", angams))
                            except KeyError:
                                logging.debug(('%', festival_name, ': ', festival_rules[festival_name.split('\\')[0][:-1]]))
                                logging.debug(("%%angams today & tmrw:", angams))

                        if priority == 'paraviddha':
                            if (angams[1] == angam_num and angams[3] == angam_num) or (angams[2] == angam_num and angams[3] == angam_num):
                                # Incident at kaala on two consecutive days; so take second
                                fday = d + 1
                            elif angams[0] == angam_num and angams[1] == angam_num:
                                # Incident only on day 1, maybe just touching day 2
                                fday = d
                            elif angams[1] == angam_num:
                                fday = d
                                if debug_festivals:
                                    logging.warning('%s %d did not touch start of %s kaala on d=%d or %d,\
                                        but incident at end of kaala at d=%d. Assigning %d for %s; angams: %s' %
                                                    (angam_type, angam_num, kaala, d, d + 1, d, fday, festival_name, str(angams)))
                            elif angams[2] == angam_num:
                                fday = d
                                if debug_festivals:
                                    logging.warning('%s %d present only at start of %s kaala on d=%d. Assigning %d for %s; angams: %s' %
                                                    (angam_type, angam_num, kaala, d + 1, d, festival_name, str(angams)))
                            elif angams[0] == angam_num and angams[1] == next_angam:
                                if kaala == 'aparaahna':
                                    fday = d
                                else:
                                    fday = d - 1
                            elif angams[1] == prev_angam and angams[2] == next_angam:
                                fday = d
                                logging.warning('%s %d did not touch %s kaala on d=%d or %d. Assigning %d for %s; angams: %s' %
                                                (angam_type, angam_num, kaala, d, d + 1, fday, festival_name, str(angams)))
                            else:
                                if festival_name not in self.fest_days and angams[3] > angam_num:
                                    logging.debug((angams, angam_num))
                                    logging.warning('Could not assign paraviddha day for %s!  Please check for unusual cases.' % festival_name)
                        elif priority == 'puurvaviddha':
                            # angams_yest = self.get_angams_for_kaalas(d - 1, get_angam_func, kaala)
                            # if debug_festivals:
                            #     print("%angams yest & today:", angams_yest)
                            if angams[0] == angam_num or angams[1] == angam_num:
                                if festival_name in self.fest_days:
                                    # Check if yesterday was assigned already
                                    # to this puurvaviddha festival!
                                    if self.fest_days[festival_name].count(d - 1) == 0:
                                        fday = d
                                else:
                                    fday = d
                            elif angams[2] == angam_num or angams[3] == angam_num:
                                fday = d + 1
                            else:
                                # This means that the correct angam did not
                                # touch the kaala on either day!
                                if angams == [prev_angam, prev_angam, next_angam, next_angam]:
                                    # d_offset = {'sunrise': 0, 'aparaahna': 1, 'moonrise': 1, 'madhyaahna': 1, 'sunset': 1}[kaala]
                                    d_offset = 0 if kaala in ['sunrise', 'moonrise'] else 1
                                    if debug_festivals:
                                        logging.warning(
                                            '%d-%02d-%02d> %s: %s %d did not touch %s on either day: %s. Assigning today + %d' %
                                            (y, m, dt, festival_name, angam_type, angam_num, kaala, str(angams), d_offset))
                                    # Need to assign a day to the festival here
                                    # since the angam did not touch kaala on either day
                                    # BUT ONLY IF YESTERDAY WASN'T ALREADY ASSIGNED,
                                    # THIS BEING PURVAVIDDHA
                                    # Perhaps just need better checking of
                                    # conditions instead of this fix
                                    if festival_name in self.fest_days:
                                        if self.fest_days[festival_name].count(d - 1 + d_offset) == 0:
                                            fday = d + d_offset
                                    else:
                                        fday = d + d_offset
                                else:
                                    if festival_name not in self.fest_days and angams != [prev_angam] * 4:
                                        logging.debug('Special case: %s; angams = %s' % (festival_name, str(angams)))

                        elif priority == 'vyaapti':
                            if kaala == 'aparaahna':
                                t_start_d, t_end_d = temporal.get_kaalas(self.jd_sunrise[d], self.jd_sunset[d], 3, 5)
                            else:
                                logging.error('Unknown kaala: %s.' % festival_name)

                            if kaala == 'aparaahna':
                                t_start_d1, t_end_d1 = temporal.get_kaalas(self.jd_sunrise[d + 1], self.jd_sunset[d + 1], 3, 5)
                            else:
                                logging.error('Unknown kaala: %s.' % festival_name)

                            # Combinations
                            # <a> 0 0 1 1: d + 1
                            # <d> 0 1 1 1: d + 1
                            # <g> 1 1 1 1: d + 1
                            # <b> 0 0 1 2: d + 1
                            # <c> 0 0 2 2: d + 1
                            # <e> 0 1 1 2: vyApti
                            # <f> 0 1 2 2: d
                            # <h> 1 1 1 2: d
                            # <i> 1 1 2 2: d
                            p, q, r = prev_angam, angam_num, next_angam  # short-hand
                            if angams in ([p, p, q, q], [p, q, q, q], [q, q, q, q], [p, p, q, r], [p, p, r, r]):
                                fday = d + 1
                            elif angams in ([p, q, r, r], [q, q, q, r], [q, q, r, r]):
                                fday = d
                            elif angams == [p, q, q, r]:
                                angam, angam_end = angam_data[d][0]
                                assert t_start_d < angam_end < t_end_d
                                vyapti_1 = t_end_d - angam_end
                                angam_d1, angam_end_d1 = angam_data[d + 1][0]
                                assert t_start_d1 < angam_end_d1 < t_end_d1
                                vyapti_2 = angam_end - t_start_d1
                                for [angam, angam_end] in angam_data[d + 1]:
                                    if angam_end is None:
                                        pass
                                    elif t_start_d1 < angam_end < t_end_d1:
                                        vyapti_2 = angam_end - t_start_d1

                                if vyapti_2 > vyapti_1:
                                    fday = d + 1
                                else:
                                    fday = d
                        else:
                            logging.error('Unknown priority "%s" for %s! Check the rules!' % (priority, festival_name))

                    if fday is not None:
                        if (month_type == 'lunar_month' and ((self.lunar_month[d] == month_num or month_num == 0) or ((self.lunar_month[d + 1] == month_num and angam_num == 1)))) or \
                           (month_type == 'solar_month' and (self.solar_month[fday] == month_num or month_num == 0)):
                            # If month on fday is incorrect, we ignore and move.
                            if month_type == 'lunar_month' and angam_num == 1 and self.lunar_month[fday + 1] != month_num:
                                continue
                            # if festival_name.find('\\') == -1 and \
                            #         'kaala' in festival_rules[festival_name] and \
                            #         festival_rules[festival_name]['kaala'] == 'arunodaya':
                            #     fday += 1
                            self.add_festival(festival_name, fday, debug_festivals)
                        else:
                            if debug_festivals:
                                if month_type == 'solar_month':
                                    logging.warning('Not adding festival %s on %d fday (month = %d instead of %d)' % (festival_name, fday, self.solar_month[fday], month_num))
                                else:
                                    logging.warning('Not adding festival %s on %d fday (month = %d instead of %d)' % (festival_name, fday, self.lunar_month[fday], month_num))

    def assign_vishesha_vyatipata(self, debug_festivals=False):
        vs_list = self.fest_days['vyatIpAta-zrAddham']
        for d in vs_list:
            if self.solar_month[d] == 9:
                self.fest_days['vyatIpAta-zrAddham'].remove(d)
                festival_name = 'mahAdhanurvyatIpAta-zrAddham'
                self.add_festival(festival_name, d, debug_festivals)
            elif self.solar_month[d] == 6:
                self.fest_days['vyatIpAta-zrAddham'].remove(d)
                festival_name = 'mahAvyatIpAta-zrAddham'
                self.add_festival(festival_name, d, debug_festivals)

    def assign_festival_numbers(self, festival_rules, debug_festivals=False):
        # Update festival numbers if they exist
        solar_y_start_d = []
        lunar_y_start_d = []
        for d in range(1, self.duration + 1):
            if self.solar_month[d] == 1 and self.solar_month[d - 1] != 1:
                solar_y_start_d.append(d)
            if self.lunar_month[d] == 1 and self.lunar_month[d - 1] != 1:
                lunar_y_start_d.append(d)

        period_start_year = self.start_date[0]
        for festival_name in festival_rules:
            if festival_name in self.fest_days and 'year_start' in festival_rules[festival_name]:
                fest_start_year = festival_rules[festival_name]['year_start']
                month_type = festival_rules[festival_name]['month_type']
                if len(self.fest_days[festival_name]) > 1:
                    if self.fest_days[festival_name][1] - self.fest_days[festival_name][0] < 300:
                        # Lunar festivals can repeat after 354 days; Solar festivals "can" repeat after 330 days
                        # (last day of Dhanur masa Jan and first day of Dhanur masa Dec may have same nakshatra and are about 335 days apart)
                        # In fact they will be roughly 354 days apart, again!
                        logging.warning('Multiple occurrences of festival %s within year. Check?: %s' % (festival_name, str(self.fest_days[festival_name])))
                for assigned_day in self.fest_days[festival_name]:
                    if month_type == 'solar_month':
                        fest_num = period_start_year + 3100 - fest_start_year + 1
                        for start_day in solar_y_start_d:
                            if assigned_day >= start_day:
                                fest_num += 1
                    elif month_type == 'lunar_month':
                        if festival_rules[festival_name]['angam_number'] == 1 and festival_rules[festival_name]['month_number'] == 1:
                            # Assigned day may be less by one, since prathama may have started after sunrise
                            # Still assume assigned_day >= lunar_y_start_d!
                            fest_num = period_start_year + 3100 - fest_start_year + 1
                            for start_day in lunar_y_start_d:
                                if assigned_day >= start_day:
                                    fest_num += 1
                        else:
                            fest_num = period_start_year + 3100 - fest_start_year + 1
                            for start_day in lunar_y_start_d:
                                if assigned_day >= start_day:
                                    fest_num += 1

                    if fest_num <= 0:
                        logging.warning('Festival %s is only in the future!' % festival_name)
                    else:
                        if festival_name not in self.fest_days:
                            logging.warning('Did not find festival %s to be assigned. Dhanurmasa festival?' % festival_name)
                            continue
                        festival_name_updated = festival_name + '~\\#{%d}' % fest_num
                        # logging.debug('Changing %s to %s' % (festival_name, festival_name_updated))
                        if festival_name_updated in self.fest_days:
                            logging.warning('Overwriting festival day for %s %d with %d.' % (festival_name_updated, self.fest_days[festival_name_updated][0], assigned_day))
                            self.fest_days[festival_name_updated] = [assigned_day]
                        else:
                            self.fest_days[festival_name_updated] = [assigned_day]
                del(self.fest_days[festival_name])

    def cleanup_festivals(self, debug_festivals=False):
        # If tripurotsava coincides with maha kArttikI (kRttikA nakShatram)
        # only then it is mahAkArttikI
        # else it is only tripurotsava
        if 'tripurOtsavaH' not in self.fest_days:
            logging.error('tripurOtsavaH not in self.fest_days!')
        else:
            if self.fest_days['tripurOtsavaH'] != self.fest_days['mahA~kArttikI']:
                logging.warning('Removing mahA~kArttikI (%d) since it does not coincide with tripurOtsavaH (%d)' % (self.fest_days['tripurOtsavaH'][0], self.fest_days['mahA~kArttikI'][0]))
                del self.fest_days['mahA~kArttikI']
                # An error here implies the festivals were not assigned: adhika
                # mAsa calc errors??

    def compute_festivals(self, debug_festivals=False):
        self.assign_chandra_darshanam(debug_festivals=debug_festivals)
        self.assign_chaturthi_vratam(debug_festivals=debug_festivals)
        self.assign_shasthi_vratam(debug_festivals=debug_festivals)
        self.assign_vishesha_saptami(debug_festivals=debug_festivals)
        self.assign_ekadashi_vratam(debug_festivals=debug_festivals)
        self.assign_mahadwadashi(debug_festivals=debug_festivals)
        self.assign_pradosha_vratam(debug_festivals=debug_festivals)
        self.assign_vishesha_trayodashi(debug_festivals=debug_festivals)
        self.assign_gajachhaya_yoga(debug_festivals=debug_festivals)
        self.assign_mahodaya_ardhodaya(debug_festivals=debug_festivals)
        self.assign_agni_nakshatram(debug_festivals=debug_festivals)
        self.assign_tithi_vara_yoga(debug_festivals=debug_festivals)
        self.assign_bhriguvara_subrahmanya_vratam(debug_festivals=debug_festivals)
        self.assign_masa_vara_yoga_vratam(debug_festivals=debug_festivals)
        self.assign_nakshatra_vara_yoga_vratam(debug_festivals=debug_festivals)
        self.assign_ayanam(debug_festivals=debug_festivals)
        self.assign_month_day_festivals(debug_festivals=debug_festivals)
        self.assign_ayushman_bava_saumya_yoga(debug_festivals=debug_festivals)

        # ASSIGN ALL FESTIVALS FROM adyatithi submodule
        # festival_rules = read_old_festival_rules_dict(os.path.join(CODE_ROOT, 'panchangam/data/festival_rules_test.json'))
        festival_rules = read_old_festival_rules_dict(os.path.join(CODE_ROOT, 'panchangam/temporal/festival/legacy/festival_rules.json'))
        assert "tripurOtsavaH" in festival_rules
        self.assign_festivals_from_rules(festival_rules, debug_festivals=debug_festivals)
        self.assign_vishesha_vyatipata(debug_festivals=debug_festivals)
        self.assign_festival_numbers(festival_rules, debug_festivals=debug_festivals)
        self.assign_amavasya_yoga(debug_festivals=debug_festivals)
        self.cleanup_festivals(debug_festivals=debug_festivals)
        self.assign_relative_festivals()

    def assign_relative_festivals(self):
        # Add "RELATIVE" festivals --- festivals that happen before or
        # after other festivals with an exact timedelta!
        if 'yajurvEda-upAkarma' not in self.fest_days:
            logging.error('yajurvEda-upAkarma not in festivals!')
        else:
            # Extended for longer calendars where more than one upAkarma may be there
            self.fest_days['varalakSmI-vratam'] = []
            for d in self.fest_days['yajurvEda-upAkarma']:
                self.fest_days['varalakSmI-vratam'].append(d - ((self.weekday_start - 1 + d - 5) % 7))
            # self.fest_days['varalakSmI-vratam'] = [self.fest_days['yajurvEda-upAkarma'][0] -
            #                                        ((self.weekday_start - 1 + self.fest_days['yajurvEda-upAkarma'][
            #                                            0] - 5) % 7)]

        relative_festival_rules = read_old_festival_rules_dict(
            os.path.join(CODE_ROOT, 'panchangam/temporal/festival/legacy/relative_festival_rules.json'))

        for festival_name in relative_festival_rules:
            offset = int(relative_festival_rules[festival_name]['offset'])
            rel_festival_name = relative_festival_rules[festival_name]['anchor_festival_id']
            if rel_festival_name not in self.fest_days:
                # Check approx. match
                matched_festivals = []
                for fest_key in self.fest_days:
                    if fest_key.startswith(rel_festival_name):
                        matched_festivals += [fest_key]
                if matched_festivals == []:
                    logging.error('Relative festival %s not in fest_days!' % rel_festival_name)
                elif len(matched_festivals) > 1:
                    logging.error('Relative festival %s not in fest_days! Found more than one approximate match: %s' % (rel_festival_name, str(matched_festivals)))
                else:
                    self.fest_days[festival_name] = [x + offset for x in self.fest_days[matched_festivals[0]]]
            else:
                self.fest_days[festival_name] = [x + offset for x in self.fest_days[rel_festival_name]]

        for festival_name in self.fest_days:
            for j in range(0, len(self.fest_days[festival_name])):
                self.festivals[self.fest_days[festival_name][j]].append(festival_name)

    def filter_festivals(self, incl_tags=['CommonFestivals', 'MonthlyVratam', 'RareDays', 'AmavasyaDays', 'Dashavataram', 'SunSankranti']):
        festival_rules_main = read_old_festival_rules_dict(os.path.join(CODE_ROOT, 'panchangam/temporal/festival/legacy/festival_rules.json'))
        festival_rules_rel = read_old_festival_rules_dict(os.path.join(CODE_ROOT, 'panchangam/temporal/festival/legacy/relative_festival_rules.json'))
        festival_rules_desc_only = read_old_festival_rules_dict(os.path.join(CODE_ROOT, 'panchangam/temporal/festival/legacy/festival_rules_desc_only.json'))

        festival_rules = {**festival_rules_main, **festival_rules_rel, **festival_rules_desc_only}

        for d in range(1, len(self.festivals)):
            if len(self.festivals[d]) > 0:
                # Eliminate repeat festivals on the same day, and keep the list arbitrarily sorted
                self.festivals[d] = sorted(list(set(self.festivals[d])))

                def chk_fest(fest_title):
                    fest_num_loc = fest_title.find('~\#')
                    if fest_num_loc != -1:
                        fest_text_itle = fest_title[:fest_num_loc]
                    else:
                        fest_text_itle = fest_title
                    if fest_text_itle in festival_rules:
                        tag_list = (festival_rules[fest_text_itle]['tags'].split(','))
                        if set(tag_list).isdisjoint(set(incl_tags)):
                            return True
                        else:
                            return False
                    else:
                        return False

                self.festivals[d][:] = filterfalse(chk_fest, self.festivals[d])

    def calc_nakshatra_tyajyam(self, debug_tyajyam=False):
        self.tyajyam_data = [[] for _x in range(self.duration + 1)]
        if self.nakshatram_data[0] is None:
            self.nakshatram_data[0] = temporal.get_angam_data(self.jd_sunrise[0], self.jd_sunrise[1], temporal.NAKSHATRAM, ayanamsha_id=self.ayanamsha_id)
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)
            jd = self.jd_midnight[d]
            t_start = self.nakshatram_data[d - 1][-1][1]
            if t_start is not None:
                n, t_end = self.nakshatram_data[d][0]
                if t_end is None:
                    t_end = self.nakshatram_data[d + 1][0][1]
                tyajyam_start = t_start + (t_end - t_start) / 60 * (temporal.TYAJYAM_SPANS_REL[n - 1] - 1)
                tyajyam_end = t_start + (t_end - t_start) / 60 * (temporal.TYAJYAM_SPANS_REL[n - 1] + 3)
                if tyajyam_start < self.jd_sunrise[d]:
                    self.tyajyam_data[d - 1] += [(tyajyam_start, tyajyam_end)]
                    if debug_tyajyam:
                        logging.debug('![%3d]%04d-%02d-%02d: %s (>>%s), %s–%s' %
                                      (d - 1, y, m, dt - 1, temporal.NAMES['NAKSHATRAM_NAMES']['hk'][n],
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (t_end - self.jd_midnight[d - 1])).toString(format='hh:mm*'),
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (tyajyam_start - self.jd_midnight[d - 1])).toString(format='hh:mm*'),
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (tyajyam_end - self.jd_midnight[d - 1])).toString(format='hh:mm*')))
                else:
                    self.tyajyam_data[d] = [(tyajyam_start, tyajyam_end)]
                    if debug_tyajyam:
                        logging.debug(' [%3d]%04d-%02d-%02d: %s (>>%s), %s–%s' %
                                      (d, y, m, dt, temporal.NAMES['NAKSHATRAM_NAMES']['hk'][n],
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (t_end - jd)).toString(format='hh:mm*'),
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (tyajyam_start - jd)).toString(format='hh:mm*'),
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (tyajyam_end - jd)).toString(format='hh:mm*')))

            if len(self.nakshatram_data[d]) == 2:
                t_start = t_end
                n2, t_end = self.nakshatram_data[d][1]
                tyajyam_start = t_start + (t_end - t_start) / 60 * (temporal.TYAJYAM_SPANS_REL[n2 - 1] - 1)
                tyajyam_end = t_start + (t_end - t_start) / 60 * (temporal.TYAJYAM_SPANS_REL[n2 - 1] + 3)
                self.tyajyam_data[d] += [(tyajyam_start, tyajyam_end)]
                if debug_tyajyam:
                    logging.debug(' [%3d]            %s (>>%s), %s–%s' %
                                  (d, temporal.NAMES['NAKSHATRAM_NAMES']['hk'][n2],
                                   jyotisha.panchangam.temporal.hour.Hour(24 * (t_end - jd)).toString(format='hh:mm*'),
                                   jyotisha.panchangam.temporal.hour.Hour(24 * (tyajyam_start - jd)).toString(format='hh:mm*'),
                                   jyotisha.panchangam.temporal.hour.Hour(24 * (tyajyam_end - jd)).toString(format='hh:mm*')))

    def calc_nakshatra_amrita(self, debug_amrita=False):
        self.amrita_data = [[] for _x in range(self.duration + 1)]
        if self.nakshatram_data[0] is None:
            self.nakshatram_data[0] = temporal.get_angam_data(self.jd_sunrise[0], self.jd_sunrise[1], temporal.NAKSHATRAM, ayanamsha_id=self.ayanamsha_id)
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)
            jd = self.jd_midnight[d]
            t_start = self.nakshatram_data[d - 1][-1][1]
            if t_start is not None:
                n, t_end = self.nakshatram_data[d][0]
                if t_end is None:
                    t_end = self.nakshatram_data[d + 1][0][1]
                amrita_start = t_start + (t_end - t_start) / 60 * (temporal.AMRITA_SPANS_REL[n - 1] - 1)
                amrita_end = t_start + (t_end - t_start) / 60 * (temporal.AMRITA_SPANS_REL[n - 1] + 3)
                if amrita_start < self.jd_sunrise[d]:
                    self.amrita_data[d - 1] += [(amrita_start, amrita_end)]
                    if debug_amrita:
                        logging.debug('![%3d]%04d-%02d-%02d: %s (>>%s), %s–%s' %
                                      (d - 1, y, m, dt - 1, temporal.NAMES['NAKSHATRAM_NAMES']['hk'][n],
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (t_end - self.jd_midnight[d - 1])).toString(format='hh:mm*'),
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (amrita_start - self.jd_midnight[d - 1])).toString(format='hh:mm*'),
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (amrita_end - self.jd_midnight[d - 1])).toString(format='hh:mm*')))
                else:
                    self.amrita_data[d] = [(amrita_start, amrita_end)]
                    if debug_amrita:
                        logging.debug(' [%3d]%04d-%02d-%02d: %s (>>%s), %s–%s' %
                                      (d, y, m, dt, temporal.NAMES['NAKSHATRAM_NAMES']['hk'][n],
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (t_end - jd)).toString(format='hh:mm*'),
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (amrita_start - jd)).toString(format='hh:mm*'),
                                       jyotisha.panchangam.temporal.hour.Hour(24 * (amrita_end - jd)).toString(format='hh:mm*')))

            if len(self.nakshatram_data[d]) == 2:
                t_start = t_end
                n2, t_end = self.nakshatram_data[d][1]
                amrita_start = t_start + (t_end - t_start) / 60 * (temporal.AMRITA_SPANS_REL[n2 - 1] - 1)
                amrita_end = t_start + (t_end - t_start) / 60 * (temporal.AMRITA_SPANS_REL[n2 - 1] + 3)
                self.amrita_data[d] += [(amrita_start, amrita_end)]
                if debug_amrita:
                    logging.debug(' [%3d]            %s (>>%s), %s–%s' %
                                  (d, temporal.NAMES['NAKSHATRAM_NAMES']['hk'][n2],
                                   jyotisha.panchangam.temporal.hour.Hour(24 * (t_end - jd)).toString(format='hh:mm*'),
                                   jyotisha.panchangam.temporal.hour.Hour(24 * (amrita_start - jd)).toString(format='hh:mm*'),
                                   jyotisha.panchangam.temporal.hour.Hour(24 * (amrita_end - jd)).toString(format='hh:mm*')))

    def assign_shraaddha_tithi(self, debug_shraaddha_tithi=False):
        def _assign(self, fday, tithi):
            if self.shraaddha_tithi[fday] == [None] or self.shraaddha_tithi[fday] == [tithi]:
                self.shraaddha_tithi[fday] = [tithi]
            else:
                self.shraaddha_tithi[fday].append(tithi)
                if self.shraaddha_tithi[fday - 1].count(tithi) == 1:
                    self.shraaddha_tithi[fday - 1].remove(tithi)
        nDays = self.len
        self.shraaddha_tithi = [[None] for _x in range(nDays)]
        for d in range(1, self.duration + 1):
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(self.jd_start_utc + d - 1)

            angams = self.get_angams_for_kaalas(d, temporal.get_tithi, 'aparaahna')
            angam_start = angams[0]
            next_angam = (angam_start % 30) + 1
            nnext_angam = (next_angam % 30) + 1

            # Calc vyaaptis
            t_start_d, t_end_d = temporal.get_kaalas(self.jd_sunrise[d], self.jd_sunset[d], 3, 5)
            vyapti_1 = t_end_d - t_start_d
            vyapti_2 = 0
            for [tithi, tithi_end] in self.tithi_data[d]:
                if tithi_end is None:
                    pass
                elif t_start_d < tithi_end < t_end_d:
                    vyapti_1 = tithi_end - t_start_d
                    vyapti_2 = t_end_d - tithi_end

            t_start_d1, t_end_d1 = temporal.get_kaalas(self.jd_sunrise[d + 1], self.jd_sunset[d + 1], 3, 5)
            vyapti_3 = t_end_d1 - t_start_d1
            for [tithi, tithi_end] in self.tithi_data[d + 1]:
                if tithi_end is None:
                    pass
                elif t_start_d1 < tithi_end < t_end_d1:
                    vyapti_3 = tithi_end - t_start_d1

            # Combinations
            # <a> 1 1 1 1 - d + 1: 1
            # <b> 1 1 2 2 - d: 1
            # <f> 1 1 2 3 - d: 1, d+1: 2
            # <e> 1 1 1 2 - d, or vyApti (just in case next day aparahna is slightly longer): 1
            # <d> 1 1 3 3 - d: 1, 2
            # <h> 1 2 3 3 - d: 2
            # <c> 1 2 2 2 - d + 1: 2
            # <g> 1 2 2 3 - vyApti: 2
            fday = -1
            reason = '?'
            # if angams[1] == angam_start:
            #     logging.debug('Pre-emptively assign %2d to %3d, can be removed tomorrow if need be.' % (angam_start, d))
            #     _assign(self, d, angam_start)
            if angams[3] == angam_start:  # <a>
                # Full aparaahnas on both days, so second day
                fday = d + 1
                s_tithi = angam_start
                reason = '%2d incident on consecutive days; paraviddhA' % s_tithi
            elif (angams[1] == angam_start) and (angams[2] == next_angam):  # <b>/<f>
                fday = d
                s_tithi = angams[0]
                reason = '%2d not incident on %3d' % (s_tithi, d + 1)
                if angams[3] == nnext_angam:  # <f>
                    if debug_shraaddha_tithi:
                        logging.debug('%03d [%4d-%02d-%02d]: %s' % (d, y, m, dt, 'Need to assign %2d to %3d as it is present only at start of aparAhna tomorrow!)' % (next_angam, d + 1)))
                    _assign(self, d + 1, next_angam)
            elif angams[2] == angam_start:  # <e>
                if vyapti_1 > vyapti_3:
                    # Most likely
                    fday = d
                    s_tithi = angams[2]
                    reason = '%2d has more vyApti on day %3d (%f ghatikAs; full?) compared to day %3d (%f ghatikAs)' % (s_tithi, d, vyapti_1 * 60, d + 1, vyapti_3 * 60)
                else:
                    fday = d + 1
                    s_tithi = angams[2]
                    reason = '%2d has more vyApti on day %3d (%f ghatikAs) compared to day %3d (%f ghatikAs) --- unusual!' % (s_tithi, d + 1, vyapti_3 * 60, d, vyapti_1 * 60)
            elif angams[2] == nnext_angam:  # <d>/<h>
                if angams[1] == next_angam:  # <h>
                    fday = d
                    s_tithi = angams[1]
                    reason = '%2d has some vyApti on day %3d; not incident on day %3d at all' % (s_tithi, d, d + 1)
                else:  # <d>
                    s_tithi = angam_start
                    fday = d
                    reason = '%2d is incident fully at aparAhna today (%3d), and not incident tomorrow (%3d)!' % (s_tithi, d, d + 1)
                    # Need to check vyApti of next_angam in sAyaMkAla: if it's nearly entire sAyaMkAla ie 5-59-30 or more!
                    if debug_shraaddha_tithi:
                        logging.debug('%03d [%4d-%02d-%02d]: %s' % (d, y, m, dt, '%2d not incident at aparAhna on either day (%3d/%3d); picking second day %3d!' % (next_angam, d, d + 1, d + 1)))
                    _assign(self, d + 1, next_angam)
                    # logging.debug(reason)
            elif angams[1] == angams[2] == angams[3] == next_angam:  # <c>
                s_tithi = next_angam
                fday = d + 1
                reason = '%2d has more vyApti on %3d (full) compared to %3d (part)' % (s_tithi, d + 1, d)
            elif angams[1] == angams[2] == next_angam:  # <g>
                s_tithi = angams[2]
                if vyapti_2 > vyapti_3:
                    # Most likely
                    fday = d
                    reason = '%2d has more vyApti on day %3d (%f ghatikAs) compared to day %3d (%f ghatikAs)' % (s_tithi, d, vyapti_2 * 60, d + 1, vyapti_3 * 60)
                else:
                    fday = d + 1
                    reason = '%2d has more vyApti on day %3d (%f ghatikAs) compared to day %3d (%f ghatikAs)' % (s_tithi, d + 1, vyapti_3 * 60, d, vyapti_2 * 60)            # Examine for greater vyApti
            else:
                logging.error('Should not reach here ever! %s' % str(angams))
                reason = '?'
            if debug_shraaddha_tithi:
                logging.debug('%03d [%4d-%02d-%02d]: Assigning tithi %2d to %3d (%s).' % (d, y, m, dt, s_tithi, fday, reason))
            _assign(self, fday, s_tithi)

        if debug_shraaddha_tithi:
            logging.debug(self.shraaddha_tithi)

        self.lunar_tithi_days = {}
        for z in set(self.lunar_month):
            self.lunar_tithi_days[z] = {}
        for d in range(1, self.duration + 1):
            for t in self.shraaddha_tithi[d]:
                self.lunar_tithi_days[self.lunar_month[d]][t] = d

        # Following this primary assignment, we must now "clean" for Sankranti, and repetitions
        # If there are two tithis, take second. However, if the second has sankrAnti dushtam, take
        # first. If both have sankrAnti dushtam, take second.
        self.tithi_days = [{z: [] for z in range(1, 31)} for _x in range(13)]
        for d in range(1, self.duration + 1):
            if self.shraaddha_tithi[d] != [None]:
                if self.solar_month_end_time[d] is not None:
                    if debug_shraaddha_tithi:
                        logging.debug((d, self.solar_month_end_time[d]))
                    aparaahna_start, aparaahna_end = temporal.get_kaalas(self.jd_sunrise[d], self.jd_sunset[d], 3, 5)
                    m1 = self.solar_month[d - 1]  # Previous month
                    m2 = self.solar_month[d]  # Current month
                    if aparaahna_start < self.solar_month_end_time[d] < aparaahna_end:
                        if debug_shraaddha_tithi:
                            logging.debug('Sankranti in aparaahna! Assigning to both months!')
                        assert self.solar_month_day[d] == 1
                        for t in self.shraaddha_tithi[d]:
                            # Assigning to both months --- should get eliminated because of a second occurrence
                            self.tithi_days[m1][t].extend([d, '*'])
                            self.tithi_days[m2][t].extend([d, '*'])
                    if self.solar_month_end_time[d] < aparaahna_start:
                        if debug_shraaddha_tithi:
                            logging.debug('Sankranti before aparaahna!')
                        assert self.solar_month_day[d] == 1
                        for t in self.shraaddha_tithi[d]:
                            self.tithi_days[m2][t].extend([d, '*'])
                    if aparaahna_end < self.solar_month_end_time[d]:
                        if debug_shraaddha_tithi:
                            logging.debug('Sankranti after aparaahna!')
                        # Depending on whether sankranti is before or after sunset, m2 may or may not be equal to m1
                        # In any case, we wish to assign this tithi to the previous month, where it really occurs.
                        for t in self.shraaddha_tithi[d]:
                            self.tithi_days[m1][t].extend([d, '*'])
                else:
                    for t in self.shraaddha_tithi[d]:
                        self.tithi_days[self.solar_month[d]][t].append(d)

        # We have now assigned all tithis. Now, remove duplicates based on the above-mentioned rules.
        # TODO: This is not the best way to clean. Need to examine one month at a time.
        for m in range(1, 13):
            for t in range(1, 31):
                if len(self.tithi_days[m][t]) == 1:
                    continue
                elif len(self.tithi_days[m][t]) == 2:
                    if self.tithi_days[m][t][1] == '*':
                        # Only one tithi available!
                        if debug_shraaddha_tithi:
                            logging.debug('Only one %2d tithi in month %2d, on day %3d, despite sankrAnti dushtam!' % (t, m, self.tithi_days[m][t][0]))
                        del self.tithi_days[m][t][1]
                        self.tithi_days[m][t][0] = '%d::%d' % (self.tithi_days[m][t][0], m)
                        if debug_shraaddha_tithi:
                            logging.debug('Note %s' % str(self.tithi_days[m][t]))
                    else:
                        self.shraaddha_tithi[self.tithi_days[m][t][0]] = [0]  # Shunya
                        if debug_shraaddha_tithi:
                            logging.debug('Removed %d' % self.tithi_days[m][t][0])
                        del self.tithi_days[m][t][0]
                        if debug_shraaddha_tithi:
                            logging.debug('Two %2d tithis in month %2d: retaining second on %2d!' % (t, m, self.tithi_days[m][t][0]))
                elif len(self.tithi_days[m][t]) == 3:
                    if debug_shraaddha_tithi:
                        logging.debug('Two %2d tithis in month %2d: %s' % (t, m, str(self.tithi_days[m][t])))
                    if self.tithi_days[m][t][1] == '*':
                        self.shraaddha_tithi[self.tithi_days[m][t][0]] = [0]  # Shunya
                        if debug_shraaddha_tithi:
                            logging.debug('Removed %d' % self.tithi_days[m][t][0])
                        del self.tithi_days[m][t][:2]
                    elif self.tithi_days[m][t][2] == '*':
                        self.shraaddha_tithi[self.tithi_days[m][t][1]] = [0]  # Shunya
                        if debug_shraaddha_tithi:
                            logging.debug('Removed %d' % self.tithi_days[m][t][1])
                        del self.tithi_days[m][t][1:]
                        if debug_shraaddha_tithi:
                            logging.debug('     Retaining non-dushta: %s' % (str(self.tithi_days[m][t])))
                elif len(self.tithi_days[m][t]) == 4:
                    if debug_shraaddha_tithi:
                        logging.debug('Two dushta %2d tithis in month %2d: %s' % (t, m, str(self.tithi_days[m][t])))
                    self.shraaddha_tithi[self.tithi_days[m][t][0]] = [0]  # Shunya
                    if debug_shraaddha_tithi:
                        logging.debug('Removed %d' % self.tithi_days[m][t][0])
                    self.tithi_days[m][t][3] = str(m)
                    del self.tithi_days[m][t][:2]
                    if debug_shraaddha_tithi:
                        logging.debug('                    Retaining: %s' % (str(self.tithi_days[m][t])))
                    self.tithi_days[m][t][0] = '%d::%d' % (self.tithi_days[m][t][0], m)
                    if debug_shraaddha_tithi:
                        logging.debug('Note %s' % str(self.tithi_days[m][t]))
                elif len(self.tithi_days[m][t]) == 0:
                    logging.warning('Rare issue. No tithi %d in this solar month (%d). Therefore use lunar tithi.' % (t, m))
                    # सौरमासे तिथ्यलाभे चान्द्रमानेन कारयेत्
                    # self.tithi_days[m][t] = self.lunar_tithi_days[m][t]
                else:
                    logging.error('Something weird. len(self.tithi_days[m][t]) is not in 1:4!! : %s (m=%d, t=%d)', str(self.tithi_days[m][t]), m, t)

            if debug_shraaddha_tithi:
                logging.debug(self.tithi_days)

    def compute_solar_eclipses(self):
        # Set location
        swe.set_topo(lon=self.city.longitude, lat=self.city.latitude, alt=0.0)
        jd = self.jd_start_utc
        while 1:
            next_eclipse_sol = swe.sol_eclipse_when_loc(julday=jd, lon=self.city.longitude, lat=self.city.latitude)
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(next_eclipse_sol[1][0])
            local_time = tz(self.city.timezone).localize(datetime(y, m, dt, 6, 0, 0))
            # checking @ 6am local - can we do any better?
            tz_off = (datetime.utcoffset(local_time).days * 86400 +
                      datetime.utcoffset(local_time).seconds) / 3600.0
            # compute offset from UTC
            jd = next_eclipse_sol[1][0] + (tz_off / 24.0)
            jd_eclipse_solar_start = next_eclipse_sol[1][1] + (tz_off / 24.0)
            jd_eclipse_solar_end = next_eclipse_sol[1][4] + (tz_off / 24.0)
            # -1 is to not miss an eclipse that occurs after sunset on 31-Dec!
            if jd_eclipse_solar_start > self.jd_end_utc + 1:
                break
            else:
                fday = int(floor(jd) - floor(self.jd_start_utc) + 1)
                if (jd < (self.jd_sunrise[fday] + tz_off / 24.0)):
                    fday -= 1
                eclipse_solar_start = temporal.jd_to_utc_gregorian(jd_eclipse_solar_start)[3]
                eclipse_solar_end = temporal.jd_to_utc_gregorian(jd_eclipse_solar_end)[3]
                if (jd_eclipse_solar_start - (tz_off / 24.0)) == 0.0 or \
                        (jd_eclipse_solar_end - (tz_off / 24.0)) == 0.0:
                    # Move towards the next eclipse... at least the next new
                    # moon (>=25 days away)
                    jd += temporal.MIN_DAYS_NEXT_ECLIPSE
                    continue
                if eclipse_solar_end < eclipse_solar_start:
                    eclipse_solar_end += 24
                sunrise_eclipse_day = temporal.jd_to_utc_gregorian(self.jd_sunrise[fday] + (tz_off / 24.0))[3]
                sunset_eclipse_day = temporal.jd_to_utc_gregorian(self.jd_sunset[fday] + (tz_off / 24.0))[3]
                if eclipse_solar_start < sunrise_eclipse_day:
                    eclipse_solar_start = sunrise_eclipse_day
                if eclipse_solar_end > sunset_eclipse_day:
                    eclipse_solar_end = sunset_eclipse_day
                solar_eclipse_str = 'sUrya-grahaNam' + \
                                    '~\\textsf{' + jyotisha.panchangam.temporal.hour.Hour(eclipse_solar_start).toString(format=self.fmt) + \
                                    '}{\\RIGHTarrow}\\textsf{' + jyotisha.panchangam.temporal.hour.Hour(eclipse_solar_end).toString(format=self.fmt) + '}'
                if self.weekday[fday] == 0:
                    solar_eclipse_str = '★cUDAmaNi-' + solar_eclipse_str
                self.festivals[fday].append(solar_eclipse_str)
            jd = jd + temporal.MIN_DAYS_NEXT_ECLIPSE

    def compute_lunar_eclipses(self):
        # Set location
        swe.set_topo(lon=self.city.longitude, lat=self.city.latitude, alt=0.0)
        jd = self.jd_start_utc
        while 1:
            next_eclipse_lun = swe.lun_eclipse_when(jd)
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(next_eclipse_lun[1][0])
            local_time = tz(self.city.timezone).localize(datetime(y, m, dt, 6, 0, 0))
            # checking @ 6am local - can we do any better? This is crucial,
            # since DST changes before 6 am
            tz_off = (datetime.utcoffset(local_time).days * 86400 +
                      datetime.utcoffset(local_time).seconds) / 3600.0
            # compute offset from UTC
            jd = next_eclipse_lun[1][0] + (tz_off / 24.0)
            jd_eclipse_lunar_start = next_eclipse_lun[1][2] + (tz_off / 24.0)
            jd_eclipse_lunar_end = next_eclipse_lun[1][3] + (tz_off / 24.0)
            # -1 is to not miss an eclipse that occurs after sunset on 31-Dec!
            if jd_eclipse_lunar_start > self.jd_end_utc:
                break
            else:
                eclipse_lunar_start = temporal.jd_to_utc_gregorian(jd_eclipse_lunar_start)[3]
                eclipse_lunar_end = temporal.jd_to_utc_gregorian(jd_eclipse_lunar_end)[3]
                if (jd_eclipse_lunar_start - (tz_off / 24.0)) == 0.0 or \
                        (jd_eclipse_lunar_end - (tz_off / 24.0)) == 0.0:
                    # Move towards the next eclipse... at least the next full
                    # moon (>=25 days away)
                    jd += temporal.MIN_DAYS_NEXT_ECLIPSE
                    continue
                fday = int(floor(jd_eclipse_lunar_start) - floor(self.jd_start_utc) + 1)
                # print '%%', jd, fday, self.jd_sunrise[fday],
                # self.jd_sunrise[fday-1]
                if (jd < (self.jd_sunrise[fday] + tz_off / 24.0)):
                    fday -= 1
                if eclipse_lunar_start < temporal.jd_to_utc_gregorian(self.jd_sunrise[fday + 1] + tz_off / 24.0)[3]:
                    eclipse_lunar_start += 24
                # print '%%', jd, fday, self.jd_sunrise[fday],
                # self.jd_sunrise[fday-1], eclipse_lunar_start,
                # eclipse_lunar_end
                jd_moonrise_eclipse_day = swe.rise_trans(
                    jd_start=self.jd_sunrise[fday], body=swe.MOON, lon=self.city.longitude,
                    lat=self.city.latitude, rsmi=CALC_RISE)[1][0] + (tz_off / 24.0)
                jd_moonset_eclipse_day = swe.rise_trans(
                    jd_start=jd_moonrise_eclipse_day, body=swe.MOON, lon=self.city.longitude,
                    lat=self.city.latitude, rsmi=CALC_SET)[1][0] + (tz_off / 24.0)

                if eclipse_lunar_end < eclipse_lunar_start:
                    eclipse_lunar_end += 24

                if jd_eclipse_lunar_end < jd_moonrise_eclipse_day or \
                        jd_eclipse_lunar_start > jd_moonset_eclipse_day:
                    # Move towards the next eclipse... at least the next full
                    # moon (>=25 days away)
                    jd += temporal.MIN_DAYS_NEXT_ECLIPSE
                    continue

                moonrise_eclipse_day = temporal.jd_to_utc_gregorian(jd_moonrise_eclipse_day)[3]
                moonset_eclipse_day = temporal.jd_to_utc_gregorian(jd_moonset_eclipse_day)[3]

                if jd_eclipse_lunar_start < jd_moonrise_eclipse_day:
                    eclipse_lunar_start = moonrise_eclipse_day
                if jd_eclipse_lunar_end > jd_moonset_eclipse_day:
                    eclipse_lunar_end = moonset_eclipse_day

                if swe.calc_ut(jd_eclipse_lunar_end, swe.MOON)[0][0] < swe.calc_ut(jd_eclipse_lunar_end, swe.SUN)[0][0]:
                    grasta = 'rAhugrasta'
                else:
                    grasta = 'kEtugrasta'

                lunar_eclipse_str = 'candra-grahaNam~(' + grasta + ')' + \
                                    '~\\textsf{' + jyotisha.panchangam.temporal.hour.Hour(eclipse_lunar_start).toString(format=self.fmt) + \
                                    '}{\\RIGHTarrow}\\textsf{' + jyotisha.panchangam.temporal.hour.Hour(eclipse_lunar_end).toString(format=self.fmt) + '}'
                if self.weekday[fday] == 1:
                    lunar_eclipse_str = '★cUDAmaNi-' + lunar_eclipse_str

                self.festivals[fday].append(lunar_eclipse_str)
            jd += temporal.MIN_DAYS_NEXT_ECLIPSE

    def computeTransits(self):
        jd_end = self.jd_start_utc + self.duration
        check_window = 400  # Max t between two Jupiter transits is ~396 (checked across 180y)
        # Let's check for transitions in a relatively large window
        # to finalise what is the FINAL transition post retrograde movements
        transits = temporal.get_planet_next_transit(self.jd_start_utc, jd_end + check_window,
                                                    swe.JUPITER, ayanamsha_id=self.ayanamsha_id)
        if len(transits) > 0:
            for i, (jd_transit, rashi1, rashi2) in enumerate(transits):
                if self.jd_start_utc < jd_transit < jd_end:
                    fday = int(floor(jd_transit) - floor(self.jd_start_utc) + 1)
                    self.festivals[fday].append('guru-saGkrAntiH~(%s##\\To{}##%s)' %
                                                (temporal.NAMES['RASHI_NAMES']['hk'][rashi1],
                                                 temporal.NAMES['RASHI_NAMES']['hk'][rashi2]))
                    if rashi1 < rashi2 and transits[i + 1][1] < transits[i + 1][2]:
                        # Considering only non-retrograde transits for pushkara computations
                        # logging.debug('Non-retrograde transit; we have a pushkaram!')
                        (madhyanha_start, madhyaahna_end) = temporal.get_kaalas(self.jd_sunrise[fday],
                                                                                self.jd_sunset[fday], 2, 5)
                        if jd_transit < madhyaahna_end:
                            fday_pushkara = fday
                        else:
                            fday_pushkara = fday + 1
                        self.add_festival('%s-Adi-puSkara-ArambhaH' % temporal.NAMES['PUSHKARA_NAMES']['hk'][rashi2],
                                          fday_pushkara, debug=False)
                        self.add_festival('%s-Adi-puSkara-samApanam' % temporal.NAMES['PUSHKARA_NAMES']['hk'][rashi2],
                                          fday_pushkara + 11, debug=False)
                        self.add_festival('%s-antya-puSkara-samApanam' % temporal.NAMES['PUSHKARA_NAMES']['hk'][rashi1],
                                          fday_pushkara - 1, debug=False)
                        self.add_festival('%s-antya-puSkara-ArambhaH' % temporal.NAMES['PUSHKARA_NAMES']['hk'][rashi1],
                                          fday_pushkara - 12, debug=False)

        # transits = temporal.get_planet_next_transit(self.jd_start, jd_end,
        #                                    swe.SATURN, ayanamsha_id=self.ayanamsha_id)
        # if len(transits) > 0:
        #     for jd_transit, rashi1, rashi2 in transits:
        #         fday = int(floor(jd_transit) - floor(self.jd_start) + 1)
        #         self.festivals[fday].append('zani-saGkrAntiH~(%s##\\To{}##%s)' %
        #                                     (temporal.NAMES['RASHI']['hk'][rashi1],
        #                                     temporal.NAMES['RASHI']['hk'][rashi2]))

    def write_debug_log(self):
        log_file = open('cal-%4d-%s-log.txt' % (self.year, self.city.name), 'w')
        for d in range(1, self.len - 1):
            jd = self.jd_start_utc - 1 + d
            [y, m, dt, t] = temporal.jd_to_utc_gregorian(jd)
            longitude_sun_sunset = swe.calc_ut(self.jd_sunset[d], swe.SUN)[0][0] - zodiac.Ayanamsha(self.ayanamsha_id).get_offset(self.jd_sunset[d])
            log_data = '%02d-%02d-%4d\t[%3d]\tsun_rashi=%8.3f\ttithi=%8.3f\tsolar_month\
        =%2d\tlunar_month=%4.1f\n' % (dt, m, y, d, (longitude_sun_sunset % 360) / 30.0,
                                      temporal.get_angam_float(self.jd_sunrise[d],
                                                               temporal.TITHI,
                                                               ayanamsha_id=self.ayanamsha_id),
                                      self.solar_month[d], self.lunar_month[d])
            log_file.write(log_data)

    def update_festival_details(self):
        """

        Festival data may be updated more frequently and a precomputed panchangam may go out of sync. Hence we keep this method separate.
        :return:
        """
        self.reset_festivals()
        self.computeTransits()
        self.compute_solar_eclipses()
        self.compute_lunar_eclipses()
        self.assign_shraaddha_tithi()
        self.compute_festivals()

    def add_details(self, compute_lagnams=False):
        self.compute_angams(compute_lagnams=compute_lagnams)
        self.assignLunarMonths()
        # self.update_festival_details()

    def reset_festivals(self, compute_lagnams=False):
        self.fest_days = {}
        # Pushkaram starting on 31 Jan might not get over till 12 days later
        self.festivals = [[] for _x in range(self.len + 15)]


# Essential for depickling to work.
common.update_json_class_index(sys.modules[__name__])


# logging.debug(common.json_class_index)


def get_panchangam(city, start_date, end_date, script, fmt='hh:mm', compute_lagnams=False, precomputed_json_dir="~/Documents", ayanamsha_id=zodiac.Ayanamsha.CHITRA_AT_180):
    fname_det = os.path.expanduser('%s/%s-%s-%s-detailed.json' % (precomputed_json_dir, city.name, start_date, end_date))
    fname = os.path.expanduser('%s/%s-%s-%s.json' % (precomputed_json_dir, city.name, start_date, end_date))

    if os.path.isfile(fname) and not compute_lagnams:
        sys.stderr.write('Loaded pre-computed panchangam from %s.\n' % fname)
        p = JsonObject.read_from_file(filename=fname)
        p.script = script  # Need to force script, in case saved file script is different
        return p
    elif os.path.isfile(fname_det):
        # Load pickle, do not compute!
        sys.stderr.write('Loaded pre-computed panchangam from %s.\n' % fname)
        p = JsonObject.read_from_file(filename=fname_det)
        p.script = script  # Need to force script, in case saved file script is different
        return p
    else:
        sys.stderr.write('No precomputed data available. Computing panchangam...\n')
        panchangam = Panchangam(city=city, start_date=start_date, end_date=end_date, script=script, fmt=fmt, compute_lagnams=compute_lagnams, ayanamsha_id=ayanamsha_id)
        sys.stderr.write('Writing computed panchangam to %s...\n' % fname)

        try:
            if compute_lagnams:
                panchangam.dump_to_file(filename=fname_det)
            else:
                panchangam.dump_to_file(filename=fname)
        except EnvironmentError:
            logging.warning("Not able to save.")
            logging.error(traceback.format_exc())
        # Save without festival details
        # Festival data may be updated more frequently and a precomputed panchangam may go out of sync. Hence we keep this method separate.
        panchangam.update_festival_details()
        return panchangam


if __name__ == '__main__':
    city = spatio_temporal.City('Chennai', "13:05:24", "80:16:12", "Asia/Calcutta")
    panchangam = Panchangam(city=city, start_date='2019-04-14', end_date='2020-04-13', script=sanscript.DEVANAGARI, ayanamsha_id=zodiac.Ayanamsha.CHITRA_AT_180, fmt='hh:mm', compute_lagnams=False)
