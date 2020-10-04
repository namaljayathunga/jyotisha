import logging
import sys

from sanskrit_data.schema import common
from sanskrit_data.schema.common import JsonObject

logging.basicConfig(
  level=logging.DEBUG,
  format="%(levelname)s: %(asctime)s {%(filename)s:%(lineno)d}: %(message)s "
)

MAX_DAYS_PER_YEAR = 366
MAX_SZ = MAX_DAYS_PER_YEAR + 6  # plus one and minus one are usually necessary


class PanchaangaApplier(JsonObject):
  """Objects of this type apply various temporal attributes to panchAnga-s."""
  def __init__(self, panchaanga):
    super().__init__()
    self.panchaanga = panchaanga
    self.daily_panchaangas = self.panchaanga.daily_panchaangas_sorted()
    self.ayanaamsha_id = panchaanga.computation_system.ayanaamsha_id

  def assign_all(self, debug=False):
    pass


class ComputationOptions(JsonObject):
  def __init__(self, lagnas=False, festivals=True, fest_ids=None):
    self.lagnas = lagnas
    self.festivals = festivals
    self.fest_ids = fest_ids
    


class ComputationSystem(JsonObject):
  def __init__(self, lunar_month_assigner_type, ayanaamsha_id, computation_options=ComputationOptions()):
    self.lunar_month_assigner_type = lunar_month_assigner_type
    self.ayanaamsha_id = ayanaamsha_id
    self.options = computation_options

  def __str__(self):
    return "%s__%s" % (self.lunar_month_assigner_type, self.ayanaamsha_id)


def set_constants():
  from jyotisha.panchaanga.temporal.month import LunarMonthAssigner
  from jyotisha.panchaanga.temporal.zodiac import Ayanamsha
  ComputationSystem.MULTI_NEW_MOON_SOLAR_MONTH_ADHIKA__CHITRA_180 = ComputationSystem(lunar_month_assigner_type=LunarMonthAssigner.MULTI_NEW_MOON_SOLAR_MONTH_ADHIKA, ayanaamsha_id=Ayanamsha.CHITRA_AT_180)
  ComputationSystem.SOLSTICE_POST_DARK_10_ADHIKA__CHITRA_180 = ComputationSystem(lunar_month_assigner_type=LunarMonthAssigner.SOLSTICE_POST_DARK_10_ADHIKA, ayanaamsha_id=Ayanamsha.CHITRA_AT_180)
  


# Essential for depickling to work.
common.update_json_class_index(sys.modules[__name__])
# logging.debug(common.json_class_index)
