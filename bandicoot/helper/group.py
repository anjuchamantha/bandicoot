from functools import partial
from datetime import timedelta
from collections import OrderedDict, Counter
import itertools

from bandicoot.helper.maths import mean, std, SummaryStats
from bandicoot.helper.tools import advanced_wrap, AutoVivification


DATE_GROUPERS = {
    None: lambda d: None,
    "day": lambda d: d.isocalendar(),
    "week": lambda d: d.isocalendar()[0:2],
    "month": lambda d: (d.year, d.month),
    "year": lambda d: d.year
}


def filter_user(user, using='records', interaction=None,
                part_of_week='allweek', part_of_day='allday'):
    """
    Filter records of a User objects by interaction, part of week and day.

    Parameters
    ----------
    user : User
        a bandicoot User object
    type : str, default 'records'
        'records' or 'recharges'
    part_of_week : {'allweek', 'weekday', 'weekend'}, default 'allweek'
        * 'weekend': keep only the weekend records
        * 'weekday': keep only the weekdays records
        * 'allweek': use all the records
    part_of_day : {'allday', 'day', 'night'}, default 'allday'
        * 'day': keep only the records during the day
        * 'night': keep only the records during the night
        * 'allday': use all the records
    interaction : object
        The interaction to filter records:
        * "callandtext", for only callandtext;
        * a string, to filter for one type;
        * None, to use all records.
    """

    if using == 'recharges':
        records = user.recharges
    else:
        records = user.records
        if interaction == 'callandtext':
            records = filter(lambda r: r.interaction in ['call', 'text'], records)
        elif interaction is not None:
            records = filter(lambda r: r.interaction == interaction, records)

    if part_of_week == 'weekday':
        records = filter(lambda r: r.datetime.isoweekday() not in user.weekend, records)
    elif part_of_week == 'weekend':
        records = filter(lambda r: r.datetime.isoweekday() in user.weekend, records)
    elif part_of_week != 'allweek':
        raise KeyError("{} is not a valid value for part_of_week. it should be 'weekday', 'weekend' or 'allweek'.".format(part_of_week))

    if user.night_start < user.night_end:
        night_filter = lambda r: user.night_end > r.datetime.time() > user.night_start
    else:
        night_filter = lambda r: not(user.night_end < r.datetime.time() < user.night_start)

    if part_of_day == 'day':
        records = filter(lambda r: not(night_filter(r)), records)
    elif part_of_day == 'night':
        records = filter(night_filter, records)
    elif part_of_day != 'allday':
        raise KeyError("{} is not a valid value for part_of_day. It should be 'day', 'night' or 'allday'.".format(part_of_day))

    return records


def positions_binning(records):
    """
    Bin records by chunks of 30 minutes, returning the most prevalent position.
    """
    def get_key(d):
        from datetime import datetime, timedelta
        k = d + timedelta(minutes=-(d.minute % 30))
        return datetime(k.year, k.month, k.day, k.hour, k.minute, 0)

    chunks = itertools.groupby(records, key=lambda r: get_key(r.datetime))

    for _, items in chunks:
        positions = [i.position for i in items]
        yield Counter(positions).most_common(1)[0][0]


def _group_range(records, method):
    """
    Yield the range of all dates between the extrema of
    a list of records, separated by a given time delta.
    """

    start_date = records[0].datetime
    end_date = records[-1].datetime
    _fun = DATE_GROUPERS[method]

    d = start_date

    # Day and week use timedelta
    if method not in ["month", "year"]:
        def increment(i):
            return i + timedelta(**{method + 's': 1})

    elif method == "month":
        def increment(i):
            year, month = divmod(i.month + 1, 12)
            if month == 0:
                month = 12
                year = year - 1
            return d.replace(year=d.year + year, month=month)

    elif method == "year":
        def increment(i):
            return d.replace(year=d.year + 1)

    while _fun(d) <= _fun(end_date):
        yield d
        d = increment(d)


def group_records_with_padding(records, groupby='week'):
    if groupby is None:
        yield records
        return

    if records == []:
        return

    _range = _group_range(records, groupby)
    _fun = DATE_GROUPERS[groupby]

    # Ad hoc grouping with padding
    pointer = next(_range)
    for key, chunk in itertools.groupby(records, key=lambda r: _fun(r.datetime)):
        chunk = list(chunk)

        while _fun(pointer) < key:
            yield []
            pointer = next(_range)

        yield chunk

        pointer = next(_range)


def group_records(records, groupby='week'):
    """
    Group records by year, month, week, or day.

    Parameters
    ----------
    records : iterator
        An iterator over records

    groupby : Default is 'week':
        * 'week': group all records by year and week
        * None: records are not grouped. This is useful if you don't want to
          divide records in chunks
        * "day", "month", and "year" also accepted
    """

    def _group_date(records, _fun):
        for _, chunk in itertools.groupby(records, key=lambda r: _fun(r.datetime)):
            yield list(chunk)

    return _group_date(records, DATE_GROUPERS[groupby])


def infer_type(data):
    """
    Infer the type of objects returned by indicators.

    infer_type returns:
     - 'scalar' for a number or None,
     - 'summarystats' for a SummaryStats object,
     - 'distribution_scalar' for a list of scalars,
     - 'distribution_summarystats' for a list of SummaryStats objects
    """

    if isinstance(data, (type(None), int, float)):
        return 'scalar'

    if isinstance(data, SummaryStats):
        return 'summarystats'

    if hasattr(data, "__len__"):  # list or numpy array
        data = filter(lambda x: x is not None, data)
        if len(data) == 0 or isinstance(data[0], (int, float)):
            return 'distribution_scalar'
        if isinstance(data[0], SummaryStats):
            return 'distribution_summarystats'

        raise TypeError("{} is not a valid input. It should be a number, a SummaryStats object, or None".format(data[0]))

    raise TypeError("{} is not a valid input. It should be a number, a SummaryStats object, or a list".format(data))


def statistics(data, summary='default', datatype=None):
    """
    Return statistics (mean, standard error, standard error and median, min and max) on data metrics.

    Examples
    --------
    Given a list of integers or floating point numbers,
    ``statistics`` computes the mean and standard error of the mean, and the min and max.

    >>> statistics([0, 1, 2, 3])
    {'mean': 1.5, 'std': 1.2910, 'min': 0, 'max': 3}

    Given a list of ``SummaryStats`` tuples, the function will
    returns the mean, standard error of the mean, min and max for each attribute
    of the tuples.
    """

    def _default_stats(agg):
        if agg is None or len(agg) == 0:
            return {'mean': None, 'std': None}
        else:
            # Some functions may return None values
            # It's better to filter them
            agg = filter(lambda x: x is not None, agg)
            return {'mean': mean(agg), 'std': std(agg)}

    def _stats_dict(v):
        return {key: _default_stats([getattr(s, key, None) for s in data]) for key in v}

    summary_keys = {
        'default': ['mean', 'std'],
        'extended': ['mean', 'std', 'median', 'skewness', 'kurtosis', 'min', 'max']
    }

    if datatype is None:
        datatype = infer_type(data)

    if datatype == 'scalar':
        return data

    if datatype == 'summarystats':
        if summary is None:
            return data.distribution
        elif summary in ['default', 'extended']:
            return {key: getattr(data, key, None) for key in summary_keys[summary]}
        else:
            raise ValueError("{} is not a valid summary type".format(summary))

    if datatype == 'distribution_scalar':
        if summary == 'default':
            return _default_stats(data)
        elif summary is None:
            return data
        else:
            raise ValueError("{} is not a valid summary type".format(summary))

    if datatype == 'distribution_summarystats':
        if summary is None:
            return [item.distribution for item in data]
        elif summary in ['extended', 'default']:
            return _stats_dict(summary_keys[summary])
        else:
            raise ValueError("{} is not a valid summary type".format(summary))

    raise ValueError("{} is not a valid data type.".format(datatype))


def _generic_wrapper(f, user, operations, datatype):
    def compute_indicator(g):
        if operations['apply']['user_kwd']:
            return f(list(g), user, **operations['apply']['kwargs'])
        else:
            return f(list(g), **operations['apply']['kwargs'])

    def _ordereddict_product(dicts):
        return [OrderedDict(zip(dicts, x)) for x in
                itertools.product(*dicts.values())]

    def map_and_apply(params_combinations):
        for params, groups in params_combinations:
            results = [compute_indicator(g) for g in groups]

            if operations['groupby'] is None:
                results = results[0] if len(results) != 0 else None

            stats = statistics(results, datatype=datatype,
                               summary=operations['apply']['summary'])

            yield params.values(), stats

    # Step 1: filter records for all possible combinations of parameters
    combinations = _ordereddict_product(operations['divide_by'])
    params_groups = [(p, filter_user(user, using=operations['using'], **p))
                     for p in combinations]

    # Step 2: group records by week, month, etc.
    if operations['filter_empty']:
        agg_function = group_records
    else:
        agg_function = group_records_with_padding

    def select_function(g):
        if operations['binning'] is True:
            return map(positions_binning, g)
        else:
            return g

    groupby = operations['groupby']
    groups = [(p, select_function(agg_function(g, groupby)))
              for p, g in params_groups]

    # Step 3: apply indicator function for each combinations
    # and return results in a nested dictionary
    returned = AutoVivification()
    for params, stats in map_and_apply(groups):
        returned.insert(params, stats)
    return returned


def divide_parameters(split_week, split_day, interaction):
    if isinstance(interaction, str):
        interaction = [interaction]

    part_of_day = ['allday']
    if split_day:
        part_of_day += ['day', 'night']

    part_of_week = ['allweek']
    if split_week:
        part_of_week += ['weekday', 'weekend']

    if interaction:
        return OrderedDict([
            ('part_of_week', part_of_week),
            ('part_of_day', part_of_day),
            ('interaction', interaction)
        ])
    else:
        return OrderedDict([
            ('part_of_week', part_of_week),
            ('part_of_day', part_of_day)
        ])


def grouping(f=None, interaction=['call', 'text'], summary='default',
             user_kwd=False):
    """
    ``grouping`` is a decorator for indicator functions, used to simplify the
    source code.

    Parameters
    ----------
    f : function
        The function to decorate
    user_kwd : boolean
        If user_kwd is True, the user object will be passed to the decorated
        function
    interaction : 'call', 'text', 'location', or a list
        By default, all indicators use only 'call' and 'text' records, but the
        interaction keywords filters the records passed to the function.
    summary: 'default', 'extended', None
        An indicator returns data statistics, ether *mean* and *std* by
        default, more with 'extended', or the inner distribution with None.
        See :meth:`~bandicoot.helper.group.statistics` for more details.

    See :ref:`new-indicator-label` to learn how to write an indicator with
    this decorator.

    """

    if f is None:
        return partial(grouping, user_kwd=user_kwd, interaction=interaction,
                       summary=summary)

    def wrapper(user, groupby='week', interaction=interaction, summary=summary,
                split_week=False, split_day=False, filter_empty=True,
                datatype=None, **kwargs):

        if interaction is None:
            interaction = ['call', 'text']
        parameters = divide_parameters(split_week, split_day, interaction)

        operations = {
            'using': 'records',
            'binning': False,
            'groupby': groupby,
            'filter_empty': filter_empty,
            'divide_by': parameters,
            'apply': {
                'user_kwd': user_kwd,
                'summary': summary,
                'kwargs': kwargs
            }
        }

        for i in parameters['interaction']:
            if i not in ['callandtext', 'call', 'text', 'location']:
                raise ValueError("%s is not a valid interaction value. Only "
                                 "'call', 'text', and 'location' are accepted."
                                 % i)

        return _generic_wrapper(f, user, operations, datatype)

    return advanced_wrap(f, wrapper)


def spatial_grouping(f=None, user_kwd=False, summary='default',
                     time_binning=True):
    if f is None:
        return partial(spatial_grouping, user_kwd=user_kwd, summary=summary,
                       time_binning=time_binning)

    def wrapper(user, groupby='week', summary=summary, split_week=False,
                split_day=False, filter_empty=True, datatype=None, **kwargs):

        parameters = divide_parameters(split_week, split_day, None)
        operations = {
            'using': 'records',
            'binning': time_binning,
            'groupby': groupby,
            'filter_empty': filter_empty,
            'divide_by': parameters,
            'apply': {
                'user_kwd': user_kwd,
                'summary': summary,
                'kwargs': kwargs
            }
        }
        return _generic_wrapper(f, user, operations, datatype)

    return advanced_wrap(f, wrapper)


def recharges_grouping(f=None, summary='default', user_kwd=False):
    if f is None:
        return partial(grouping, user_kwd=user_kwd, summary=summary)

    def wrapper(user, groupby='week', summary=summary,
                split_week=False, split_day=False, filter_empty=True,
                datatype=None, **kwargs):

        parameters = divide_parameters(split_week, split_day, None)

        operations = {
            'using': 'recharges',
            'binning': False,
            'groupby': groupby,
            'filter_empty': filter_empty,
            'divide_by': parameters,
            'apply': {
                'user_kwd': user_kwd,
                'summary': summary,
                'kwargs': kwargs
            }
        }

        return _generic_wrapper(f, user, operations, datatype)

    return advanced_wrap(f, wrapper)
