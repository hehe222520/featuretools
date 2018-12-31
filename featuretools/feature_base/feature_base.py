from featuretools.variable_types import Variable
from featuretools.primitives.base import PrimitiveBase
from featuretools.variable_types import (
    Categorical,
    Datetime,
    DatetimeTimeIndex,
    Id,
    Numeric,
    NumericTimeIndex,
    Variable
)

class FeatureBase(object):
    _name = None
    expanding = False

    def __init__(self, entity, base_features, primitive):
        assert all(isinstance(f, FeatureBase) for f in base_features), \
            "All base features must be features"
        if len(set([bf.hash() for bf in base_features])) != len(base_features):
            raise ValueError(u"Duplicate base features ({}): {}".format(
                self.__class__, base_features))

        self.entity_id = entity.id
        self.entityset = entity.entityset.metadata

        self.base_features = base_features
        self.primitive = primitive

        assert self._check_input_types(), ("Provided inputs don't match input "
                                           "type requirements")

    def _check_feature(self, feature):
        if isinstance(feature, Variable):
            return IdentityFeature(feature)
        elif isinstance(feature, FeatureBase):
            return feature
        raise Exception("Not a feature")


    def rename(self, name):
        """Rename Feature, returns copy"""
        feature_copy = self.copy()
        feature_copy._name = name
        return feature_copy

    def copy(self):
        """Return copy of feature"""
        original_attrs = {}
        copied_attrs = {}
        for k, v in self.__dict__.items():
            list_like = False
            to_check = v
            if isinstance(v, (list, set, tuple)) and len(v):
                to_check = list(v)[0]
                list_like = True
            if isinstance(to_check, PrimitiveBase):
                if list_like:
                    copied_attrs[k] = [f.copy() for f in v]
                    original_attrs[k] = [f.copy() for f in v]
                else:
                    copied_attrs[k] = v.copy()
                    original_attrs[k] = v.copy()
                setattr(self, k, None)
            elif isinstance(to_check, (Variable, Entity, EntitySet)):
                copied_attrs[k] = v
                original_attrs[k] = v
                setattr(self, k, None)
        copied = copy.deepcopy(self)
        for k, v in copied_attrs.items():
            setattr(copied, k, v)
        for k, v in original_attrs.items():
            setattr(self, k, v)
        return copied

    def get_name(self):
        if self._name is not None:
            return self._name
        return self.generate_name()

    def get_function(self):
        return self.primitive.get_function()

    def get_dependencies(self, deep=False, ignored=None, copy=True):
        """Returns features that are used to calculate this feature

        ..note::

            If you only want the features that make up the input to the feature
            function use the base_features attribute instead.


        """
        deps = []

        for d in self.base_features[:]:
            deps += [d]

        if hasattr(self, "where") and self.where:
            deps += [self.where]

        # if self.use_previous and self.use_previous.is_absolute():
            # entity = self.entity
            # time_var = IdentityFeature(entity[entity.time_index])
            # deps += [time_var]

        if ignored is None:
            ignored = set([])
        deps = [d for d in deps if d.hash() not in ignored]

        if deep:
            for dep in deps[:]:  # copy so we don't modify list we iterate over
                deep_deps = dep.get_dependencies(deep, ignored)
                deps += deep_deps

        return deps

    def get_deep_dependencies(self, ignored=None):
        return self.get_dependencies(deep=True, ignored=ignored)

    def get_depth(self, stop_at=None):
        """Returns depth of feature"""
        max_depth = 0
        stop_at_hash = set()
        if stop_at is not None:
            stop_at_hash = set([i.hash() for i in stop_at])
        if (stop_at is not None and
                self.hash() in stop_at_hash):
            return 0
        for dep in self.get_deep_dependencies(ignored=stop_at_hash):
            max_depth = max(dep.get_depth(stop_at=stop_at),
                            max_depth)
        return max_depth + 1

    def _check_input_types(self):
        if len(self.base_features) == 0:
            return True

        input_types = self.primitive.input_types
        if input_types is not None:
            if type(input_types[0]) != list:
                input_types = [input_types]

            for t in input_types:
                zipped = list(zip(t, self.base_features))
                if all([issubclass(f.variable_type, v) for v, f in zipped]):
                    return True
        else:
            return True

        return False

    @property
    def entity(self):
        """Entity this feature belongs too"""
        return self.entityset[self.entity_id]

    def __repr__(self):
        ret = "<Feature: %s>" % (self.get_name())

        # encode for python 2
        if type(ret) != str:
            ret = ret.encode("utf-8")

        return ret

    def hash(self):
        return hash(self.get_name() + self.entity.id)

    def __hash__(self):
        # logger.warning("To hash a feature, use feature.hash()")
        return self.hash()

    @property
    def variable_type(self):
        feature = self
        variable_type = self.primitive.return_type

        while variable_type is None:
            # get variable_type of first base feature
            base_feature = feature.base_features[0]
            variable_type = base_feature.variable_type

            # only the original time index should exist
            # so make this feature's return type just a Datetime
            if variable_type == DatetimeTimeIndex:
                variable_type = Datetime
            elif variable_type == NumericTimeIndex:
                variable_type = Numeric

            # direct features should keep the Id return type, but all other features should get
            # converted to Categorical
            if not isinstance(feature, DirectFeature) and variable_type == Id:
                variable_type = Categorical

            feature = base_feature

        return variable_type

    @property
    def default_value(self):
        return self.primitive.default_value

class IdentityFeature(FeatureBase):
    """Feature for entity that is equivalent to underlying variable"""

    def __init__(self, variable):
        # TODO: perhaps we can change the attributes of this class to
        # just entityset reference to original variable object
        entity_id = variable.entity_id
        self.variable = variable.entityset.metadata[entity_id][variable.id]
        self.return_type = type(variable)
        self.base_feature = None
        super(IdentityFeature, self).__init__(variable.entity, [], primitive=PrimitiveBase())

    def generate_name(self):
        return self.variable.name

    def get_depth(self, stop_at=None):
        return 0

    @property
    def variable_type(self):
        return type(self.variable)


class DirectFeature(FeatureBase):
    """Feature for child entity that inherits
        a feature value from a parent entity"""
    input_types = [Variable]
    return_type = None

    def __init__(self, base_feature, child_entity):
        self.primitive = PrimitiveBase() # TODO
        base_feature = self._check_feature(base_feature)
        if base_feature.expanding:
            self.expanding = True

        path = child_entity.entityset.find_forward_path(child_entity.id, base_feature.entity.id)
        if len(path) > 1:
            parent_entity_id = path[1].child_entity.id
            parent_entity = child_entity.entityset[parent_entity_id]
            parent_feature = DirectFeature(base_feature, parent_entity)
        else:
            parent_feature = base_feature

        self.parent_entity = parent_feature.entity
        self._variable_type = parent_feature.variable_type
        super(DirectFeature, self).__init__(child_entity, [parent_feature])

    @property
    def default_value(self):
        return self.base_features[0].default_value

    @property
    def variable(self):
        return getattr(self.base_features[0], 'variable', None)

    @property
    def variable_type(self):
        return type(self.variable)

    def generate_name(self):
        return u"%s.%s" % (self.parent_entity.id,
                           self.base_features[0].get_name())


class AggregationFeature(FeatureBase):
    #: (:class:`.PrimitiveBase`): Feature to condition this feature by in
    # computation (e.g. take the Count of products where the product_id is
    # "basketball".)
    where = None
    #: (str or :class:`.Timedelta`): Use only some amount of previous data from
    # each time point during calculation
    use_previous = None

    def __init__(self, base_features, parent_entity, use_previous=None,
                 where=None, primitive=None):
        # Any edits made to this method should also be made to the
        # new_class_init method in make_agg_primitive
        if not hasattr(base_features, '__iter__'):
            base_features = [self._check_feature(base_features)]
        else:
            base_features = [self._check_feature(bf) for bf in base_features]
            msg = "all base features must share the same entity"
            assert len(set([bf.entity for bf in base_features])) == 1, msg
        self.base_features = base_features[:]

        self.child_entity = base_features[0].entity
        self.parent_entity = parent_entity

        if where is not None:
            self.where = self._check_feature(where)
            msg = "Where feature must be defined on child entity {}".format(
                self.child_entity.id)
            assert self.where.entity.id == self.child_entity.id, msg

        if use_previous:
            assert self.child_entity.time_index is not None, (
                "Applying function that requires time index to entity that "
                "doesn't have one")

            self.use_previous = _check_timedelta(self.use_previous)
            assert len(self.base_features) > 0
            time_index = self.base_features[0].entity.time_index
            time_col = self.base_features[0].entity[time_index]
            assert time_index is not None, ("Use previous can only be defined "
                                            "on entities with a time index")
            assert _check_time_against_column(self.use_previous, time_col)

        self.use_previous = use_previous

        super(AggregationFeature, self).__init__(parent_entity,
                                                 self.base_features,
                                                 primitive=primitive)

    def _where_str(self):
        if self.where is not None:
            where_str = u" WHERE " + self.where.get_name()
        else:
            where_str = ''
        return where_str

    def _use_prev_str(self):
        if self.use_previous is not None:
            use_prev_str = u", Last {}".format(self.use_previous.get_name())
        else:
            use_prev_str = u''
        return use_prev_str

    def generate_name(self):
        return self.primitive.generate_name(base_feature_names=[bf.get_name() for bf in self.base_features],
                                            child_entity_id=self.child_entity.id,
                                            parent_entity_id=self.parent_entity.id,
                                            where_str=self._where_str(),
                                            use_prev_str=self._use_prev_str())

class TransformFeature(FeatureBase):
    def __init__(self, *base_features, primitive=None):
        # Any edits made to this method should also be made to the
        # new_class_init method in make_trans_primitive
        self.base_features = [self._check_feature(f) for f in base_features]
        if any(bf.expanding for bf in self.base_features):
            self.expanding = True
        assert len(set([f.entity for f in self.base_features])) == 1, \
            "More than one entity for base features"
        super(TransformFeature, self).__init__(self.base_features[0].entity,
                                               self.base_features, primitive=primitive)

    def generate_name(self):
        return self.primitive.generate_name(base_feature_names=[bf.get_name() for bf in self.base_features])