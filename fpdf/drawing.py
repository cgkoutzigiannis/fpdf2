from collections import OrderedDict
from contextlib import contextmanager
import enum
import decimal
import math
from typing import Optional, NamedTuple, Union

__pdoc__ = {"force_nodocument": False}


def force_nodocument(item):
    """A decorator that forces pdoc not to document the decorated item (class or method)"""
    __pdoc__[item.__qualname__] = False
    return item


@force_nodocument
def force_document(item):
    """A decorator that forces pdoc to document the decorated item (class or method)"""
    __pdoc__[item.__qualname__] = True
    return item


# type alias:
Number = Union[int, float, decimal.Decimal]

_global_style_registry = {}
# this is just a reverse mapping of the above
_global_style_name_lookup = {}


# this maybe should live in fpdf.syntax
class Raw(str):
    """str subclass signifying raw data to be directly emitted to PDF without transformation."""


class Name(str):
    """str subclass signfying a PDF name, which are emitted differently than normal strings."""


WHITESPACE = frozenset({"\0", "\t", "\n", "\f", "\r", " "})
"""Characters PDF considers to be whitespace."""
EOL_CHARS = frozenset({"\n", "\r"})
"""Characters PDF considers to mark the end of a line."""


def get_style_dict_by_name(name):
    """
    Look up the named style dictionary.

    Args:
        name (str): the name of the dictionary to look up. This should be a name taken
            from the list of style dictionaries returned by `GraphicsContext.render`.

    Raises:
        KeyError: if no dictionary with the given name exists.
    """
    return _global_style_name_lookup[name]


def _new_global_style_name():
    return Name(f"GS{len(_global_style_registry)}")


def _get_or_set_style_dict(style):
    sdict = style.to_pdf_dict()

    if not sdict:
        return None

    try:
        return _global_style_registry[sdict]
    except KeyError:
        pass

    name = _new_global_style_name()
    _global_style_registry[sdict] = name
    _global_style_name_lookup[name] = sdict

    return name


def _check_range(value, minimum=0.0, maximum=1.0):
    if not minimum <= value <= maximum:
        raise ValueError(f"{value} not in range [{minimum}, {maximum}]")

    return value


def number_to_str(number):
    """
    Convert a decimal number to a minimal string representation (no trailing 0 or .).

    Args:
        number (Number): the number to be converted to a string.

    Returns:
        The number's string representation.
    """
    # this approach tries to produce minimal representations of floating point numbers
    # but can also produce "-0".
    return ("%.4f" % number).rstrip("0").rstrip(".")


# this maybe should live in fpdf.syntax
def render_pdf_primitive(primitive):
    """
    Render a Python value as a PDF primitive type.

    Container types (tuples/lists and dicts) are rendered recursively. This supports
    values of the type Name, str, bytes, numbers, booleans, list/tuple, and dict.

    Any custom type can be passed in as long as it provides a `pdf_repr` method that
    takes no arguments and returns a string. The existence of this method is checked
    before any other type checking is performed, so, for example, a `dict` subclass
    with a `pdf_repr` method would be converted using its `pdf_repr` method rather than
    the built-in `dict` conversion process.

    Args:
        primitive: the primitive value to convert to its PDF representation.

    Returns:
        Raw-wrapped str of the PDF representation.

    Raises:
        ValueError: if a dictionary key is not a Name.
        TypeError: if `primitive` does not have a known conversion to a PDF
            representation.
    """

    if isinstance(primitive, Raw):
        output = primitive
    elif callable(getattr(primitive, "pdf_repr", None)):
        output = primitive.pdf_repr()
    elif isinstance(primitive, Name):
        # this should handle escape sequences, to be proper (#XX)
        output = f"/{primitive}"
    elif isinstance(primitive, str):
        # this should handle escape sequences, to be proper (\n \r \t \b \f \( \) \\)
        output = f"({str})"
    elif isinstance(primitive, bytes):
        output = f"<{primitive.hex()}>"
    elif isinstance(primitive, (int, float, decimal.Decimal)):
        output = number_to_str(primitive)
    elif isinstance(primitive, bool):
        output = ["false", "true"][primitive]
    elif isinstance(primitive, (list, tuple)):
        output = "[" + " ".join(render_pdf_primitive(val) for val in primitive) + "]"
    elif primitive is None:
        output = "null"
    elif isinstance(primitive, dict):
        item_list = []
        for key, val in primitive.items():
            if not isinstance(key, Name):
                raise ValueError("dict keys must be Names")

            item_list.append(
                render_pdf_primitive(key) + " " + render_pdf_primitive(val)
            )

        output = "<< " + "\n".join(item_list) + " >>"
    else:
        raise TypeError(f"cannot produce PDF representation for value {primitive!r}")

    return Raw(output)


_global_style_registry[render_pdf_primitive({Name("Type"): Name("ExtGState")})] = None


# We allow passing alpha in as None instead of a numeric quantity, which signals to the
# rendering procedure not to emit an explicit alpha field for this graphics state,
# causing it to be inherited from the parent.

# this weird inheritance is used because for some reason normal NamedTuple usage doesn't
# allow overriding __new__, even though it works just as expected this way.
class DeviceRGB(
    NamedTuple(
        "DeviceRGB",
        [("r", Number), ("g", Number), ("b", Number), ("a", Optional[Number])],
    )
):
    """A class representing a PDF DeviceRGB color."""

    # This follows a common PDF drawing operator convention where the operand is upcased
    # to apply to stroke and downcased to apply to fill.

    # This could be more manually specified by  `CS`/`cs` to set the color space(e.g. to
    # `/DeviceRGB`) and `SC`/`sc` to set the color parameters. The documentation isn't
    # perfectly clear on this front, but it appears that these cannot be set in the
    # current graphics state dictionary and instead is set in the current page resource
    # dictionary. fpdf appears to only generate a single resource dictionary for the
    # entire document, and even if it created one per page, it would still be a lot
    # clunkier to try to use that.

    # Because PDF hates me, personally, the opacity of the drawing HAS to be specified
    # in the current graphics state dictionary and does not exist as a standalone
    # directive.
    OPERATOR = "rg"
    """The PDF drawing operator used to specify this type of color."""

    def __new__(cls, r, g, b, a=None):
        if a is not None:
            _check_range(a)

        return super().__new__(
            cls, _check_range(r), _check_range(g), _check_range(b), a
        )

    @property
    def colors(self):
        """The color components as a tuple in order `(r, g, b)` with alpha omitted."""
        return self[:-1]


__pdoc__["DeviceRGB.OPERATOR"] = False
__pdoc__["DeviceRGB.r"] = "The red color component. Must be in the interval [0, 1]."
__pdoc__["DeviceRGB.g"] = "The green color component. Must be in the interval [0, 1]."
__pdoc__["DeviceRGB.b"] = "The blue color component. Must be in the interval [0, 1]."
__pdoc__[
    "DeviceRGB.a"
] = """
The alpha color component (i.e. opacity). Must be `None` or in the interval [0, 1].

An alpha value of 0 makes the color fully transparent, and a value of 1 makes it fully
opaque. If `None`, the color will be interpreted as not specifying a particular
transparency rather than specifying fully transparent or fully opaque.
"""


# this weird inheritance is used because for some reason normal NamedTuple usage doesn't
# allow overriding __new__, even though it works just as expected this way.
class DeviceGray(
    NamedTuple(
        "DeviceGray",
        [("g", Number), ("a", Optional[Number])],
    )
):
    """A class representing a PDF DeviceGray color."""

    OPERATOR = "g"
    """The PDF drawing operator used to specify this type of color."""

    def __new__(cls, g, a=None):
        if a is not None:
            _check_range(a)

        return super().__new__(cls, _check_range(g), a)

    @property
    def colors(self):
        """The color components as a tuple in order (g,) with alpha omitted."""
        return self[:-1]


__pdoc__["DeviceGray.OPERATOR"] = False
__pdoc__[
    "DeviceGray.g"
] = """
The gray color component. Must be in the interval [0, 1].

A value of 0 represents black and a value of 1 represents white.
"""
__pdoc__[
    "DeviceGray.a"
] = """
The alpha color component (i.e. opacity). Must be `None` or in the interval [0, 1].

An alpha value of 0 makes the color fully transparent, and a value of 1 makes it fully
opaque. If `None`, the color will be interpreted as not specifying a particular
transparency rather than specifying fully transparent or fully opaque.
"""


# this weird inheritance is used because for some reason normal NamedTuple usage doesn't
# allow overriding __new__, even though it works just as expected this way.
class DeviceCMYK(
    NamedTuple(
        "DeviceCMYK",
        [
            ("c", Number),
            ("m", Number),
            ("y", Number),
            ("k", Number),
            ("a", Optional[Number]),
        ],
    )
):
    """A class representing a PDF DeviceCMYK color."""

    OPERATOR = "k"
    """The PDF drawing operator used to specify this type of color."""

    def __new__(cls, c, m, y, k, a=None):
        if a is not None:
            _check_range(a)

        return super().__new__(
            cls, _check_range(c), _check_range(m), _check_range(y), _check_range(k), a
        )

    @property
    def colors(self):
        """The color components as a tuple in order (c, m, y, k) with alpha omitted."""

        return self[:-1]


__pdoc__["DeviceCMYK.OPERATOR"] = False
__pdoc__["DeviceCMYK.c"] = "The cyan color component. Must be in the interval [0, 1]."
__pdoc__[
    "DeviceCMYK.m"
] = "The magenta color component. Must be in the interval [0, 1]."
__pdoc__["DeviceCMYK.y"] = "The yellow color component. Must be in the interval [0, 1]."
__pdoc__["DeviceCMYK.k"] = "The black color component. Must be in the interval [0, 1]."
__pdoc__[
    "DeviceCMYK.a"
] = """
The alpha color component (i.e. opacity). Must be `None` or in the interval [0, 1].

An alpha value of 0 makes the color fully transparent, and a value of 1 makes it fully
opaque. If `None`, the color will be interpreted as not specifying a particular
transparency rather than specifying fully transparent or fully opaque.
"""


def rgb8(r, g, b, a=None):
    """
    Produce a DeviceRGB color from the given 8-bit RGB values.

    Args:
        r (Number): red color component. Must be in the interval [0, 255].
        g (Number): green color component. Must be in the interval [0, 255].
        b (Number): blue color component. Must be in the interval [0, 255].
        a (Optional[Number]): alpha component. Must be `None` or in the interval
            [0, 255]. 0 is fully transparent, 255 is fully opaque

    Returns:
        DeviceRGB color representation.

    Raises:
        ValueError: if any components are not in their valid interval.
    """
    if a is not None:
        a /= 255.0

    return DeviceRGB(r / 255.0, g / 255.0, b / 255.0, a)


def gray8(g, a=None):
    """
    Produce a DeviceGray color from the given 8-bit gray value.

    Args:
        g (Number): gray color component. Must be in the interval [0, 255]. 0 is black,
            255 is white.
        a (Optional[Number]): alpha component. Must be `None` or in the interval
            [0, 255]. 0 is fully transparent, 255 is fully opaque

    Returns:
        DeviceGray color representation.

    Raises:
        ValueError: if any components are not in their valid interval.
    """
    if a is not None:
        a /= 255.0

    return DeviceGray(g / 255.0, a)


def cmyk8(c, m, y, k, a=None):
    """
    Produce a DeviceCMYK color from the given 8-bit CMYK values.

    Args:
        c (Number): red color component. Must be in the interval [0, 255].
        m (Number): green color component. Must be in the interval [0, 255].
        y (Number): blue color component. Must be in the interval [0, 255].
        k (Number): blue color component. Must be in the interval [0, 255].
        a (Optional[Number]): alpha component. Must be `None` or in the interval
            [0, 255]. 0 is fully transparent, 255 is fully opaque

    Returns:
        DeviceCMYK color representation.

    Raises:
        ValueError: if any components are not in their valid interval.
    """
    if a is not None:
        a /= 255.0

    return DeviceCMYK(c / 255.0, m / 255.0, y / 255.0, k / 255.0, a)


def color_from_hex_string(hexstr):
    """
    Parse an RGB color from a css-style 8-bit hexadecimal color string.

    Args:
        hexstr (str): of the form `#RGB`, `#RGBA`, `#RRGGBB`, or `#RRGGBBAA`. Must
            include the leading octothorp. Forms omitting the alpha field are
            interpreted as not specifying the opacity, so it will not be explicitly set.

            An alpha value of `00` is fully transparent and `FF` is fully opaque.

    Returns:
        DeviceRGB representation of the color.
    """
    if not isinstance(hexstr, str):
        raise TypeError(f"{hexstr} is not of type str")

    if not hexstr.startswith("#"):
        raise ValueError(f"{hexstr} does not start with #")

    hlen = len(hexstr)

    if hlen == 4:
        return rgb8(*[int(char * 2, base=16) for char in hexstr[1:]], a=None)

    if hlen == 5:
        return rgb8(*[int(char * 2, base=16) for char in hexstr[1:]])

    if hlen == 7:
        return rgb8(
            *[int(hexstr[idx : idx + 2], base=16) for idx in range(1, hlen, 2)], a=None
        )

    if hlen == 9:
        return rgb8(*[int(hexstr[idx : idx + 2], base=16) for idx in range(1, hlen, 2)])

    raise ValueError(f"{hexstr} could not be interpreted as a RGB(A) hex string")


class Point(NamedTuple):
    """
    An x-y coordinate pair within the two-dimensional coordinate frame.
    """

    x: Number
    """The abscissa of the point."""

    y: Number
    """The ordinate of the point."""

    def render(self):
        """Render the point to the string `"x y"` for emitting to a PDF."""

        return f"{number_to_str(self.x)} {number_to_str(self.y)}"

    def dot(self, other):
        """
        Compute the dot product of two points.

        Args:
            other (Point): the point with which to compute the dot product.

        Returns:
            The scalar result of the dot product computation.

        Raises:
            TypeError: if `other` is not a `Point`.
        """
        if not isinstance(other, Point):
            raise TypeError(f"cannot dot with {other!r}")

        return self.x * other.x + self.y * other.y

    def angle(self, other):
        """
        Compute the angle between two points (interpreted as vectors from the origin).

        The return value is in the interval (-pi, pi]. Sign is dependent on ordering,
        with clockwise angle travel considered to be positive due to the orientation of
        the coordinate frame basis vectors (i.e. the angle between `(1, 0)` and `(0, 1)`
        is `+pi/2`, the angle between `(1, 0)` and `(0, -1)` is `-pi/2`, and the angle
        between `(0, -1)` and `(1, 0)` is `+pi/2`).

        Args:
            other (Point): the point to compute the angle sweep toward.

        Returns:
            The scalar angle between the two points **in radians**.

        Raises:
            TypeError: if `other` is not a `Point`.
        """

        if not isinstance(other, Point):
            raise TypeError(f"cannot compute angle with {other!r}")

        signifier = (self.x * other.y) - (self.y * other.x)
        sign = (signifier >= 0) - (signifier < 0)
        return sign * math.acos(round(self.dot(other) / (self.mag() * other.mag()), 8))

    def mag(self):
        """
        Compute the Cartesian distance from this point to the origin

        This is the same as computing the magnitude of the vector represented by this
        point.

        Returns:
            The scalar result of the distance computation.
        """

        return (self.x ** 2 + self.y ** 2) ** 0.5

    @force_document
    def __add__(self, other):
        """
        Produce the sum of two points.

        Adding two points is the same as translating the source point by interpreting
        the other point's x and y coordinates as distances.

        Args:
            other (Point): right-hand side of the infix addition operation

        Returns:
            A Point which is the sum of the two source points.
        """
        if isinstance(other, Point):
            return Point(x=self.x + other.x, y=self.y + other.y)

        return NotImplemented

    @force_document
    def __sub__(self, other):
        """
        Produce the difference between two points.

        Unlike addition, this is not a commutative operation!

        Args:
            other (Point): right-hand side of the infix subtraction operation

        Returns:
            A Point which is the difference of the two source points.
        """
        if isinstance(other, Point):
            return Point(x=self.x - other.x, y=self.y - other.y)

        return NotImplemented

    @force_document
    def __neg__(self):
        """
        Produce a point by negating this point's coordinates.

        Returns:
            A Point whose coordinates are this points coordinates negated.
        """
        return Point(x=-self.x, y=-self.y)

    @force_document
    def __mul__(self, other):
        """
        Multiply a point by a scalar value.

        Args:
            other (Number): the scalar value by which to multiply the point's
                coordinates.

        Returns:
            A Point whose coordinates are the result of the multiplication.
        """
        if isinstance(other, (int, float, decimal.Decimal)):
            return Point(self.x * other, self.y * other)

        return NotImplemented

    __rmul__ = __mul__

    @force_document
    def __div__(self, other):
        """
        Divide a point by a scalar value.

        .. note::

            Because division is not commutative, `Point / scalar` is implemented, but
            `scalar / Point` is nonsensical and not implemented.

        Args:
            other (Number): the scalar value by which to divide the point's coordinates.

        Returns:
            A Point whose coordinates are the result of the division.
        """
        if isinstance(other, (int, float, decimal.Decimal)):
            return Point(self.x / other, self.y / other)

        return NotImplemented

    # no __rdiv__ because division is not commutative!

    @force_document
    def __matmul__(self, other):
        """
        Transform a point with the given transform matrix.

        .. note::
            This operator is only implemented for Transforms. This transform is not
            commutative, so `Point @ Transform` is implemented, but `Transform @ Point`
            is not implemented (technically speaking, the current implementation is
            commutative because of the way points and transforms are represented, but
            if that representation were to change this operation could stop being
            commutative)

        Args:
            other (Transform): the transform to apply to the point

        Returns:
            A Point whose coordinates are the result of applying the transform.
        """
        if isinstance(other, Transform):
            return Point(
                x=other.a * self.x + other.c * self.y + other.e,
                y=other.b * self.x + other.d * self.y + other.f,
            )

        return NotImplemented

    def __str__(self):
        return f"(x={number_to_str(self.x)}, y={number_to_str(self.y)})"


class Transform(NamedTuple):
    """
    A representation of an affine transformation matrix for 2D shapes.

    The actual matrix is:

    ```
                        [ a b 0 ]
    [x' y' 1] = [x y 1] [ c d 0 ]
                        [ e f 1 ]
    ```

    Complex transformation operations can be composed via a sequence of simple
    transformations by performing successive matrix multiplication of the simple
    transformations.

    For example, scaling a set of points around a specific center point can be
    represented by a translation-scale-translation sequence, where the first
    translation translates the center to the origin, the scale transform scales the
    points relative to the origin, and the second translation translates the points
    back to the specified center point. Transform multiplication is performed using
    python's dedicated matrix multiplication operator, `@`

    The semantics of this representation mean composed transformations are specified
    left-to-right in order of application (some other systems provide transposed
    representations, in which case the application order is right-to-left).

    For example, to rotate the square `(1,1) (1,3) (3,3) (3,1)` 45 degrees clockwise
    about its center point (which is `(2,2)`) , the translate-rotate-translate
    process described above may be applied:

    ```python
    rotate_centered = (
        Transform.translation(-2, -2)
        @ Transform.rotation_d(45)
        @ Transform.translation(2, 2)
    )
    ```

    Instances of this class provide a chaining API, so the above transform could also be
    constructed as follows:

    ```python
    rotate_centered = Transform.translation(-2, -2).rotate_d(45).translate(2, 2)
    ```

    Or, because the particular operation of performing some transformations about a
    specific point is pretty common,

    ```python
    rotate_centered = Transform.rotation_d(45).about(2, 2)
    ```

    By convention, this class provides class method constructors following noun-ish
    naming (`translation`, `scaling`, `rotation`, `shearing`) and instance method
    manipulations following verb-ish naming (`translate`, `scale`, `rotate`, `shear`).
    """

    a: Number
    b: Number
    c: Number
    d: Number
    e: Number
    f: Number

    # compact representation of an affine transformation matrix for 2D shapes.
    # The actual matrix is:
    #                     [ A B 0 ]
    # [x' y' 1] = [x y 1] [ C D 0 ]
    #                     [ E F 1 ]
    # The identity transform is 1 0 0 1 0 0

    @classmethod
    def identity(cls):
        """
        Create a transform representing the identity transform.

        The identity transform is a no-op.
        """
        return cls(1, 0, 0, 1, 0, 0)

    @classmethod
    def translation(cls, x, y):
        """
        Create a transform that performs translation.

        Args:
            x (Number): distance to translate points along the x (horizontal) axis.
            y (Number): distance to translate points along the y (vertical) axis.

        Returns:
            A Transform representing the specified translation.
        """

        return cls(1, 0, 0, 1, x, y)

    @classmethod
    def scaling(cls, x, y=None):
        """
        Create a transform that performs scaling.

        Args:
            x (Number): scaling ratio in the x (horizontal) axis. A value of 1
                results in no scale change in the x axis.
            y (Number): optional scaling ratio in the y (vertical) axis. A value of 1
                results in no scale change in the y axis. If this value is omitted, it
                defaults to the value provided to the `x` argument.

        Returns:
            A Transform representing the specified scaling.
        """
        if y is None:
            y = x

        return cls(x, 0, 0, y, 0, 0)

    @classmethod
    def rotation(cls, theta):
        """
        Create a transform that performs rotation.

        Args:
            theta (Number): the angle **in radians** by which to rotate. Positive
                values represent clockwise rotations.

        Returns:
            A Transform representing the specified rotation.

        """
        return cls(
            math.cos(theta), math.sin(theta), -math.sin(theta), math.cos(theta), 0, 0
        )

    @classmethod
    def rotation_d(cls, theta_d):
        """
        Create a transform that performs rotation **in degrees**.

        Args:
            theta_d (Number): the angle **in degrees** by which to rotate. Positive
                values represent clockwise rotations.

        Returns:
            A Transform representing the specified rotation.

        """
        return cls.rotation(math.radians(theta_d))

    @classmethod
    def shearing(cls, x, y=None):
        """
        Create a transform that performs shearing (not of sheep).

        Args:
            x (Number): The amount to shear along the x (horizontal) axis.
            y (Number): Optional amount to shear along the y (vertical) axis. If omitted,
                this defaults to the value provided to the `x` argument.

        Returns:
            A Transform representing the specified shearing.

        """
        if y is None:
            y = x
        return cls(1, y, x, 1, 0, 0)

    def translate(self, x, y):
        """
        Produce a transform by composing the current transform with a translation.

        .. note::
            Transforms are immutable, so this returns a new transform rather than
            mutating self.

        Args:
            x (Number): distance to translate points along the x (horizontal) axis.
            y (Number): distance to translate points along the y (vertical) axis.

        Returns:
            A Transform representing the composed transform.
        """
        return self @ Transform.translation(x, y)

    def scale(self, x, y=None):
        """
        Produce a transform by composing the current transform with a scaling.

        .. note::
            Transforms are immutable, so this returns a new transform rather than
            mutating self.

        Args:
            x (Number): scaling ratio in the x (horizontal) axis. A value of 1
                results in no scale change in the x axis.
            y (Number): optional scaling ratio in the y (vertical) axis. A value of 1
                results in no scale change in the y axis. If this value is omitted, it
                defaults to the value provided to the `x` argument.

        Returns:
            A Transform representing the composed transform.
        """
        return self @ Transform.scaling(x, y)

    def rotate(self, theta):
        """
        Produce a transform by composing the current transform with a rotation.

        .. note::
            Transforms are immutable, so this returns a new transform rather than
            mutating self.

        Args:
            theta (Number): the angle **in radians** by which to rotate. Positive
                values represent clockwise rotations.

        Returns:
            A Transform representing the composed transform.
        """
        return self @ Transform.rotation(theta)

    def rotate_d(self, theta_d):
        """
        Produce a transform by composing the current transform with a rotation
        **in degrees**.

        .. note::
            Transforms are immutable, so this returns a new transform rather than
            mutating self.

        Args:
            theta_d (Number): the angle **in degrees** by which to rotate. Positive
                values represent clockwise rotations.

        Returns:
            A Transform representing the composed transform.
        """
        return self @ Transform.rotation_d(theta_d)

    def shear(self, x, y=None):
        """
        Produce a transform by composing the current transform with a shearing.

        .. note::
            Transforms are immutable, so this returns a new transform rather than
            mutating self.

        Args:
            x (Number): The amount to shear along the x (horizontal) axis.
            y (Number): Optional amount to shear along the y (vertical) axis. If omitted,
                this defaults to the value provided to the `x` argument.

        Returns:
            A Transform representing the composed transform.
        """
        return self @ Transform.shearing(x, y)

    def about(self, x, y):
        """
        Bracket the given transform in a pair of translations to make it appear about a
        point that isn't the origin.

        This is a useful shorthand for performing a transform like a rotation around the
        center point of an object that isn't centered at the origin.

        .. note::
            Transforms are immutable, so this returns a new transform rather than
            mutating self.

        Args:
            x (Number): the point along the x (horizontal) axis about which to transform.
            y (Number): the point along the y (vertical) axis about which to transform.

        Returns:
            A Transform representing the composed transform.
        """
        return Transform.translation(-x, -y) @ self @ Transform.translation(x, y)

    @force_document
    def __mul__(self, other):
        """
        Multiply the individual transform parameters by a scalar value.

        Args:
            other (Number): the scalar value by which to multiply the parameters

        Returns:
            A Transform with the modified parameters.
        """
        if isinstance(other, (int, float, decimal.Decimal)):
            return Transform(
                a=self.a * other,
                b=self.b * other,
                c=self.c * other,
                d=self.d * other,
                e=self.e * other,
                f=self.f * other,
            )

        return NotImplemented

    # scalar multiplication is commutative
    __rmul__ = __mul__

    @force_document
    def __matmul__(self, other):
        """
        Compose two transforms into a single transform.

        Args:
            other (Transform): the right-hand side transform of the infix operator.

        Returns:
            A Transform representing the composed transform.
        """
        if isinstance(other, Transform):
            return self.__class__(
                a=self.a * other.a + self.b * other.c,
                b=self.a * other.b + self.b * other.d,
                c=self.c * other.a + self.d * other.c,
                d=self.c * other.b + self.d * other.d,
                e=self.e * other.a + self.f * other.c + other.e,
                f=self.e * other.b + self.f * other.d + other.f,
            )

        return NotImplemented

    def render(self, last_item):
        """
        Render the transform to its PDF output representation.

        Args:
            last_item: the last path element this transform applies to

        Returns:
            A tuple of `(str, last_item)`. `last_item` is returned unchanged.
        """
        return (
            f"{number_to_str(self.a)} {number_to_str(self.b)} "
            f"{number_to_str(self.c)} {number_to_str(self.d)} "
            f"{number_to_str(self.e)} {number_to_str(self.f)} cm",
            last_item,
        )

    def __str__(self):
        return (
            f"transform: ["
            f"{number_to_str(self.a)} {number_to_str(self.b)} 0; "
            f"{number_to_str(self.c)} {number_to_str(self.d)} 0; "
            f"{number_to_str(self.e)} {number_to_str(self.f)} 1]"
        )


__pdoc__["Transform.a"] = False
__pdoc__["Transform.b"] = False
__pdoc__["Transform.c"] = False
__pdoc__["Transform.d"] = False
__pdoc__["Transform.e"] = False
__pdoc__["Transform.f"] = False


class CoerciveEnum(enum.Enum):
    """
    An enumeration that provides a helper to coerce strings into enumeration members.
    """

    @classmethod
    def coerce(cls, value):
        """
        Attempt to coerce `value` into a member of this enumeration.

        If value is already a member of this enumeration it is returned unchanged.
        Otherwise, if it is a string, attempt to convert it as an enumeration value. If
        that fails, attempt to convert it (case insensitively, by upcasing) as an
        enumeration name.

        If all different conversion attempts fail, an exception is raised.

        Args:
            value (enum.Enum, str): the value to be coerced.

        Raises:
            ValueError: if `value` is a string but neither a member by name nor value.
            TypeError: if `value`'s type is neither a member of the enumeration nor a
                string.
        """

        if isinstance(value, cls):
            return value

        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError:
                pass
            try:
                return cls[value.upper()]
            except KeyError:
                pass

            raise ValueError(f"{value} is not a valid {cls.__name__}")

        raise TypeError(f"{value} cannot convert to a {cls.__name__}")


class IntersectionRule(CoerciveEnum):
    """
    An enumeration representing the two possible PDF intersection rules.

    The intersection rule is used by the renderer to determine which points are
    considered to be inside the path and which points are outside the path. This
    primarily affects fill rendering and clipping paths.
    """

    NONZERO = "nonzero"
    """
    "The nonzero winding number rule determines whether a given point is inside a path
    by conceptually drawing a ray from that point to infinity in any direction and
    then examining the places where a segment of the path crosses the ray. Starting
    with a count of 0, the rule adds 1 each time a path segment crosses the ray from
    left to right and subtracts 1 each time a segment crosses from right to left.
    After counting all the crossings, if the result is 0, the point is outside the
    path; otherwise, it is inside."
    """
    EVENODD = "evenodd"
    """
    "An alternative to the nonzero winding number rule is the even-odd rule. This rule
    determines whether a point is inside a path by drawing a ray from that point in
    any direction and simply counting the number of path segments that cross the ray,
    regardless of direction. If this number is odd, the point is inside; if even, the
    point is outside. This yields the same results as the nonzero winding number rule
    for paths with simple shapes, but produces different results for more complex
    shapes."
    """


class PathPaintRule(CoerciveEnum):
    """
    An enumeration of the PDF drawing directives that determine how the renderer should
    paint a given path.
    """

    # the auto-close paint rules are omitted here because it's easier to just emit
    # close operators when appropriate, programmatically
    STROKE = "S"
    '''"Stroke the path."'''

    FILL_NONZERO = "f"
    """
    "Fill the path, using the nonzero winding number rule to determine the region to
    fill. Any subpaths that are open are implicitly closed before being filled."
    """

    FILL_EVENODD = "f*"
    """
    "Fill the path, using the even-odd rule to determine the region to fill. Any
    subpaths that are open are implicitly closed before being filled."
    """

    STROKE_FILL_NONZERO = "B"
    """
    "Fill and then stroke the path, using the nonzero winding number rule to determine
    the region to fill. This operator produces the same result as constructing two
    identical path objects, painting the first with `FILL_NONZERO` and the second with
    `STROKE`."
    """

    STROKE_FILL_EVENODD = "B*"
    """
    "Fill and then stroke the path, using the even-odd rule to determine the region to
    fill. This operator produces the same result as `STROKE_FILL_NONZERO`, except that
    the path is filled as if with `FILL_EVENODD` instead of `FILL_NONZERO`."
    """

    DONT_PAINT = "n"
    """
    "End the path object without filling or stroking it. This operator is a
    path-painting no-op, used primarily for the side effect of changing the current
    clipping path."
    """

    AUTO = "auto"
    """
    Automatically determine which `PathPaintRule` should be used.

    PaintedPath will select one of the above `PathPaintRule`s based on the resolved
    set/inherited values of its style property.
    """


class ClippingPathIntersectionRule(CoerciveEnum):
    """
    An enumeration of the PDF drawing directives that define a path as a clipping path.
    """

    NONZERO = "W"
    """
    "The nonzero winding number rule determines whether a given point is inside a path
    by conceptually drawing a ray from that point to infinity in any direction and
    then examining the places where a segment of the path crosses the ray. Starting
    with a count of 0, the rule adds 1 each time a path segment crosses the ray from
    left to right and subtracts 1 each time a segment crosses from right to left.
    After counting all the crossings, if the result is 0, the point is outside the
    path; otherwise, it is inside."
    """
    EVENODD = "W*"
    """
    "An alternative to the nonzero winding number rule is the even-odd rule. This rule
    determines whether a point is inside a path by drawing a ray from that point in
    any direction and simply counting the number of path segments that cross the ray,
    regardless of direction. If this number is odd, the point is inside; if even, the
    point is outside. This yields the same results as the nonzero winding number rule
    for paths with simple shapes, but produces different results for more complex
    shapes."
    """


class CoerciveIntEnum(enum.IntEnum):
    """
    An enumeration that provides a helper to coerce strings and integers into
    enumeration members.
    """

    @classmethod
    def coerce(cls, value):
        """
        Attempt to coerce `value` into a member of this enumeration.

        If value is already a member of this enumeration it is returned unchanged.
        Otherwise, if it is a string, attempt to convert it (case insensitively, by
        upcasing) as an enumeration name. Otherwise, if it is an int, attempt to
        convert it as an enumeration value.

        Otherwise, an exception is raised.

        Args:
            value (enum.IntEnum, str, int): the value to be coerced.

        Raises:
            ValueError: if `value` is an int but not a member of this enumeration.
            ValueError: if `value` is a string but not a member by name.
            TypeError: if `value`'s type is neither a member of the enumeration nor an
                int or a string.
        """
        if isinstance(value, cls):
            return value

        if isinstance(value, str):
            try:
                return cls[value.upper()]
            except KeyError:
                raise ValueError(f"{value} is not a valid {cls.__name__}") from None

        if isinstance(value, int):
            return cls(value)

        raise TypeError(f"{value} cannot convert to a {cls.__name__}")


class StrokeCapStyle(CoerciveIntEnum):
    """
    An enumeration of values defining how the end of a stroke should be rendered.

    This affects the ends of the segments of dashed strokes, as well.
    """

    BUTT = 0
    """
    "The stroke is squared off at the endpoint of the path. There is no projection
    beyond the end of the path."
    """
    ROUND = 1
    """
    "A semicircular arc with a diameter equal to the line width is drawn around the
    endpoint and filled in."
    """
    SQUARE = 2
    """
    "The stroke continues beyond the endpoint of the path for a distance equal to half
    the line width and is squared off."
    """


class StrokeJoinStyle(CoerciveIntEnum):
    """
    An enumeration of values defining how the corner joining two path components should
    be rendered.
    """

    MITER = 0
    """
    "The outer edges of the strokes for the two segments are extended until they meet at
    an angle, as in a picture frame. If the segments meet at too sharp an angle
    (as defined by the miter limit parameter), a bevel join is used instead."
    """
    ROUND = 1
    """
    "An arc of a circle with a diameter equal to the line width is drawn around the
    point where the two segments meet, connecting the outer edges of the strokes for
    the two segments. This pieslice-shaped figure is filled in, pro- ducing a rounded
    corner."
    """
    BEVEL = 2
    """
    "The two segments are finished with butt caps and the resulting notch beyond the
    ends of the segments is filled with a triangle."
    """


class BlendMode(CoerciveEnum):
    """
    An enumeration of the named standard named blend functions supported by PDF.
    """

    NORMAL = Name("Normal")
    '''"Selects the source color, ignoring the backdrop."'''
    MULTIPLY = Name("Multiply")
    '''"Multiplies the backdrop and source color values."'''
    SCREEN = Name("Screen")
    """
    "Multiplies the complements of the backdrop and source color values, then
    complements the result."
    """
    OVERLAY = Name("Overlay")
    """
    "Multiplies or screens the colors, depending on the backdrop color value. Source
    colors overlay the backdrop while preserving its highlights and shadows. The
    backdrop color is not replaced but is mixed with the source color to reflect the
    lightness or darkness of the backdrop."
    """
    DARKEN = Name("Darken")
    '''"Selects the darker of the backdrop and source colors."'''
    LIGHTEN = Name("Lighten")
    '''"Selects the lighter of the backdrop and source colors."'''
    COLOR_DODGE = Name("ColorDodge")
    """
    "Brightens the backdrop color to reflect the source color. Painting with black
     produces no changes."
    """
    COLOR_BURN = Name("ColorBurn")
    """
    "Darkens the backdrop color to reflect the source color. Painting with white
     produces no change."
    """
    HARD_LIGHT = Name("HardLight")
    """
    "Multiplies or screens the colors, depending on the source color value. The effect
    is similar to shining a harsh spotlight on the backdrop."
    """
    SOFT_LIGHT = Name("SoftLight")
    """
    "Darkens or lightens the colors, depending on the source color value. The effect is
    similar to shining a diffused spotlight on the backdrop."
    """
    DIFFERENCE = Name("Difference")
    '''"Subtracts the darker of the two constituent colors from the lighter color."'''
    EXCLUSION = Name("Exclusion")
    """
    "Produces an effect similar to that of the Difference mode but lower in contrast.
    Painting with white inverts the backdrop color; painting with black produces no
    change."
    """

    HUE = Name("Hue")
    """
    "Creates a color with the hue of the source color and the saturation and luminosity
    of the backdrop color."
    """
    SATURATION = Name("Saturation")
    """
    "Creates a color with the saturation of the source color and the hue and luminosity
    of the backdrop color. Painting with this mode in an area of the backdrop that is
    a pure gray (no saturation) produces no change."
    """
    COLOR = Name("Color")
    """
    "Creates a color with the hue and saturation of the source color and the luminosity
    of the backdrop color. This preserves the gray levels of the backdrop and is
    useful for coloring monochrome images or tinting color images."
    """
    LUMINOSITY = Name("Luminosity")
    """
    "Creates a color with the luminosity of the source color and the hue and saturation
    of the backdrop color. This produces an inverse effect to that of the Color mode."
    """


class PDFStyleKeys(enum.Enum):
    """
    An enumeration of the graphics state parameter dictionary keys.
    """

    FILL_ALPHA = Name("ca")
    BLEND_MODE = Name("BM")  # shared between stroke and fill
    STROKE_ALPHA = Name("CA")
    STROKE_ADJUSTMENT = Name("SA")
    STROKE_WIDTH = Name("LW")
    STROKE_CAP_STYLE = Name("LC")
    STROKE_JOIN_STYLE = Name("LJ")
    STROKE_MITER_LIMIT = Name("ML")
    STROKE_DASH_PATTERN = Name("D")  # array of array, number, e.g. [[1 1] 0]


class GraphicsStyle:
    """
    A class representing various style attributes that determine drawing appearance.

    This class uses the convention that the global Python singleton ellipsis (`...`) is
    exclusively used to represent values that are inherited from the parent style. This
    is to disambiguate the value None which is used for several values to signal an
    explicitly disabled style. An example of this is the fill/stroke color styles,
    which use None as hints to the auto paint style detection code.
    """

    INHERIT = ...
    """Singleton specifying a style parameter should be inherited from the parent context."""

    # order is be important here because some of these properties are entangled, e.g.
    # stroke_dash_pattern and stroke_dash_phase
    MERGE_PROPERTIES = (
        "paint_rule",
        "auto_close",
        "intersection_rule",
        "fill_color",
        "fill_opacity",
        "stroke_color",
        "stroke_opacity",
        "blend_mode",
        "stroke_width",
        "stroke_cap_style",
        "stroke_join_style",
        "stroke_miter_limit",
        "stroke_dash_pattern",
        "stroke_dash_phase",
    )
    """An ordered list of properties to use when merging two GraphicsStyles."""

    _PAINT_RULE_LOOKUP = {
        frozenset({}): PathPaintRule.DONT_PAINT,
        frozenset({"stroke"}): PathPaintRule.STROKE,
        frozenset({"fill", IntersectionRule.NONZERO}): PathPaintRule.FILL_NONZERO,
        frozenset({"fill", IntersectionRule.EVENODD}): PathPaintRule.FILL_EVENODD,
        frozenset(
            {"stroke", "fill", IntersectionRule.NONZERO}
        ): PathPaintRule.STROKE_FILL_NONZERO,
        frozenset(
            {"stroke", "fill", IntersectionRule.EVENODD}
        ): PathPaintRule.STROKE_FILL_EVENODD,
    }
    """A dictionary for resolving `PathPaintRule.AUTO`"""

    @classmethod
    def merge(cls, parent, child):
        """
        Merge parent and child into a single GraphicsStyle.

        The result contains the properties of the parent as overridden by any properties
        explicitly set on the child. If both the parent and the child specify to
        inherit a given property, that property will preserve the inherit value.
        """
        new = cls()
        for prop in cls.MERGE_PROPERTIES:
            cval = getattr(child, prop)
            if cval is not GraphicsStyle.INHERIT:
                setattr(new, prop, cval)
            else:
                setattr(new, prop, getattr(parent, prop))

        return new

    # If these are used in a nested graphics context inside of a painting path
    # operation, they are no-ops. However, they can be used for outer GraphicsContexts
    # that painting paths inherit from.
    @property
    def paint_rule(self):
        """The paint rule to use for this path/group."""

        return getattr(self, "_paint_rule", GraphicsStyle.INHERIT)

    @paint_rule.setter
    def paint_rule(self, new):
        if new is None:
            self._paint_rule = PathPaintRule.DONT_PAINT
        if new is GraphicsStyle.INHERIT:
            self._paint_rule = new
        else:
            self._paint_rule = PathPaintRule.coerce(new)

    @property
    def auto_close(self):
        """If True, unclosed paths will be automatically closed before stroking."""
        return getattr(self, "_auto_close", GraphicsStyle.INHERIT)

    @auto_close.setter
    def auto_close(self, new):
        if new not in {True, False, GraphicsStyle.INHERIT}:
            raise ValueError(
                f"auto_close must be a bool or GraphicsStyle.INHERIT, not {new}"
            )

        self._auto_close = new

    @property
    def intersection_rule(self):
        """The desired intersection rule for this path/group."""
        return getattr(self, "_intersection_rule", GraphicsStyle.INHERIT)

    @intersection_rule.setter
    def intersection_rule(self, new):
        # don't allow None for this one.
        if new is GraphicsStyle.INHERIT:
            self._intersection_rule = new
        else:
            self._intersection_rule = IntersectionRule.coerce(new)

    @property
    def fill_color(self):
        """
        The desired fill color for this path/group.

        When setting this property, if the color specifies an opacity value, that will
        be used to set the fill_opacity property as well.
        """

        # TODO: pull the opacity value and merge it into the returned color?
        return getattr(self, "_fill_color", GraphicsStyle.INHERIT)

    @fill_color.setter
    def fill_color(self, color):
        if isinstance(color, str):
            color = color_from_hex_string(color)

        if isinstance(color, (DeviceRGB, DeviceGray, DeviceCMYK)):
            self._fill_color = color
            # strip opacity
            # self._fill_color = color.__class__(*color.colors)
            if color.a is not None:
                self.fill_opacity = color.a

        elif (color is None) or (color is GraphicsStyle.INHERIT):
            self._fill_color = color

        else:
            raise TypeError(f"{color} doesn't look like a drawing color")

    @property
    def fill_opacity(self):
        """The desired fill opacity for this path/group."""
        return getattr(self, PDFStyleKeys.FILL_ALPHA.value, GraphicsStyle.INHERIT)

    @fill_opacity.setter
    def fill_opacity(self, new):
        if new not in {None, GraphicsStyle.INHERIT}:
            _check_range(new)

        setattr(self, PDFStyleKeys.FILL_ALPHA.value, new)

    @property
    def stroke_color(self):
        """
        The desired stroke color for this path/group.

        When setting this property, if the color specifies an opacity value, that will
        be used to set the fill_opacity property as well.
        """

        # TODO: pull the opacity value and merge it into the returned color?
        return getattr(self, "_stroke_color", GraphicsStyle.INHERIT)

    @stroke_color.setter
    def stroke_color(self, color):
        if isinstance(color, str):
            color = color_from_hex_string(color)

        if isinstance(color, (DeviceRGB, DeviceGray, DeviceCMYK)):
            self._stroke_color = color
            if color.a is not None:
                self.stroke_opacity = color.a

        elif (color is None) or (color is GraphicsStyle.INHERIT):
            self._stroke_color = color

        else:
            raise TypeError(f"{color} doesn't look like a drawing color")

    @property
    def stroke_opacity(self):
        """The desired stroke opacity for this path/group."""
        return getattr(self, PDFStyleKeys.STROKE_ALPHA.value, GraphicsStyle.INHERIT)

    @stroke_opacity.setter
    def stroke_opacity(self, new):
        if new not in {None, GraphicsStyle.INHERIT}:
            _check_range(new)

        setattr(self, PDFStyleKeys.STROKE_ALPHA.value, new)

    @property
    def blend_mode(self):
        """The desired blend mode for this path/group."""
        return getattr(self, PDFStyleKeys.BLEND_MODE.value, GraphicsStyle.INHERIT)

    @blend_mode.setter
    def blend_mode(self, value):
        if value is GraphicsStyle.INHERIT:
            setattr(self, PDFStyleKeys.BLEND_MODE.value, value)
        else:
            setattr(self, PDFStyleKeys.BLEND_MODE.value, BlendMode.coerce(value).value)

    @property
    def stroke_width(self):
        """The desired stroke width for this path/group."""
        return getattr(self, PDFStyleKeys.STROKE_WIDTH.value, GraphicsStyle.INHERIT)

    @stroke_width.setter
    def stroke_width(self, width):
        if not isinstance(
            width,
            (int, float, decimal.Decimal, type(None), type(GraphicsStyle.INHERIT)),
        ):
            raise TypeError(f"stroke_width must be a number, not {type(width)}")

        setattr(self, PDFStyleKeys.STROKE_WIDTH.value, width)

    @property
    def stroke_cap_style(self):
        """The desired stroke cap style for this path/group."""
        return getattr(self, PDFStyleKeys.STROKE_CAP_STYLE.value, GraphicsStyle.INHERIT)

    @stroke_cap_style.setter
    def stroke_cap_style(self, value):
        if value is GraphicsStyle.INHERIT:
            setattr(self, PDFStyleKeys.STROKE_CAP_STYLE.value, value)
        else:
            setattr(
                self, PDFStyleKeys.STROKE_CAP_STYLE.value, StrokeCapStyle.coerce(value)
            )

    @property
    def stroke_join_style(self):
        """The desired stroke join style for this path/group."""
        return getattr(
            self, PDFStyleKeys.STROKE_JOIN_STYLE.value, GraphicsStyle.INHERIT
        )

    @stroke_join_style.setter
    def stroke_join_style(self, value):
        if value is GraphicsStyle.INHERIT:
            setattr(self, PDFStyleKeys.STROKE_JOIN_STYLE.value, value)
        else:
            setattr(
                self,
                PDFStyleKeys.STROKE_JOIN_STYLE.value,
                StrokeJoinStyle.coerce(value),
            )

    @property
    def stroke_miter_limit(self):
        """The desired stroke miter limit for this path/group."""
        return getattr(
            self, PDFStyleKeys.STROKE_MITER_LIMIT.value, GraphicsStyle.INHERIT
        )

    @stroke_miter_limit.setter
    def stroke_miter_limit(self, value):
        if (value is GraphicsStyle.INHERIT) or isinstance(
            value, (int, float, decimal.Decimal)
        ):
            setattr(self, PDFStyleKeys.STROKE_MITER_LIMIT.value, value)
        else:
            raise TypeError(f"{value} is not a number")

    @property
    def stroke_dash_pattern(self):
        """The desired stroke dash pattern for this path/group."""
        result = getattr(
            self, PDFStyleKeys.STROKE_DASH_PATTERN.value, GraphicsStyle.INHERIT
        )
        if isinstance(result, tuple):
            return result[0]
        return result

    @stroke_dash_pattern.setter
    def stroke_dash_pattern(self, value):
        if isinstance(value, (float, int)):
            value = (value,)

        if isinstance(value, (list, tuple)):
            result = getattr(
                self, PDFStyleKeys.STROKE_DASH_PATTERN.value, GraphicsStyle.INHERIT
            )
            if isinstance(result, tuple):
                new = (tuple(value), result[1])
            else:
                new = (tuple(value), 0)
            setattr(self, PDFStyleKeys.STROKE_DASH_PATTERN.value, new)
        elif value is None:
            setattr(self, PDFStyleKeys.STROKE_DASH_PATTERN.value, ((), 0))
        elif value is GraphicsStyle.INHERIT:
            setattr(self, PDFStyleKeys.STROKE_DASH_PATTERN.value, value)
        else:
            raise TypeError(f"{value} cannot be interpreted as a dash pattern")

    @property
    def stroke_dash_phase(self):
        """The desired stroke dash patter phase offset for this path/group."""
        result = getattr(
            self, PDFStyleKeys.STROKE_DASH_PATTERN.value, GraphicsStyle.INHERIT
        )
        if isinstance(result, tuple):
            return result[1]

        return result

    @stroke_dash_phase.setter
    def stroke_dash_phase(self, value):
        if isinstance(value, (float, int)):
            result = getattr(
                self, PDFStyleKeys.STROKE_DASH_PATTERN.value, GraphicsStyle.INHERIT
            )
            if isinstance(result, tuple):
                setattr(
                    self, PDFStyleKeys.STROKE_DASH_PATTERN.value, (result[0], value)
                )
            else:
                raise ValueError("no dash pattern to set the phase on")
        elif value is GraphicsStyle.INHERIT:
            pass
        else:
            raise TypeError(f"{value} isn't a number")

    def to_pdf_dict(self):
        """
        Convert this style object to a PDF dictionary with appropriate style keys.

        Only explicitly specified values are emitted.
        """
        result = OrderedDict()
        result[Name("Type")] = Name("ExtGState")

        for key in PDFStyleKeys:
            value = getattr(self, key.value, GraphicsStyle.INHERIT)

            if (value is not GraphicsStyle.INHERIT) and (value is not None):
                # None is used for out-of-band signaling on these, e.g. a stroke_width
                # of None doesn't need to land here because it signals the
                # PathPaintRule auto resolution only.
                result[key.value] = value

        return render_pdf_primitive(result)

    @force_nodocument
    def resolve_paint_rule(self):
        """
        Resolve `PathPaintRule.AUTO` to a real paint rule based on this style.

        Returns:
            the resolved `PathPaintRule`.
        """
        if self.paint_rule is PathPaintRule.AUTO:
            want = set()
            if self.stroke_width is not None and self.stroke_color is not None:
                want.add("stroke")
            if self.fill_color is not None:
                want.add("fill")
                # we need to guarantee that this will not be None. The default will
                # be "nonzero".
                assert self.intersection_rule is not None
                want.add(self.intersection_rule)

            try:
                rule = self._PAINT_RULE_LOOKUP[frozenset(want)]
            except KeyError:
                # don't default to DONT_PAINT because that's almost certainly not a very
                # good default.
                rule = PathPaintRule.STROKE_FILL_NONZERO

        else:
            rule = self.paint_rule

        return rule


def _render_move(pt):
    return f"{pt.render()} m"


def _render_line(pt):
    return f"{pt.render()} l"


def _render_curve(ctrl1, ctrl2, end):
    return f"{ctrl1.render()} {ctrl2.render()} {end.render()} c"


class Move(NamedTuple):
    """
    A path move element.

    If a path has been created but not yet painted, this will create a new subpath.

    See: `PaintedPath.move_to`
    """

    pt: Point
    """The point to which to move."""

    @property
    def end_point(self):
        """The end point of this path element."""
        return self.pt

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is `self`
        """
        # pylint: disable=unused-argument
        return _render_move(self.pt), self

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `Move.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(str(self) + "\n")

        return rendered, resolved


class RelativeMove(NamedTuple):
    """
    A path move element with an end point relative to the end of the previous path
    element.

    If a path has been created but not yet painted, this will create a new subpath.

    See: `PaintedPath.move_relative`
    """

    pt: Point
    """The offset by which to move."""

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is the resolved
            `Move`
        """
        # pylint: disable=unused-argument
        point = last_item.end_point + self.pt
        return _render_move(point), Move(point)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `RelativeMove.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {resolved}\n")

        return rendered, resolved


class Line(NamedTuple):
    """
    A path line element.

    This draws a straight line from the end point of the previous path element to the
    point specified by `pt`.

    See: `PaintedPath.line_to`
    """

    pt: Point
    """The point to which the line is drawn."""

    @property
    def end_point(self):
        """The end point of this path element."""
        return self.pt

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is `self`
        """
        # pylint: disable=unused-argument
        return _render_line(self.pt), self

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `Line.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(str(self) + "\n")

        return rendered, resolved


class RelativeLine(NamedTuple):
    """
    A path line element with an endpoint relative to the end of the previous element.

    This draws a straight line from the end point of the previous path element to the
    point specified by `last_item.end_point + pt`. The absolute coordinates of the end
    point are resolved during the rendering process.

    See: `PaintedPath.line_relative`
    """

    pt: Point
    """The endpoint of the line relative to the previous path element."""

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is the resolved
            `Line`.
        """
        # pylint: disable=unused-argument
        point = last_item.end_point + self.pt
        return _render_line(point), Line(point)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `RelativeLine.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {resolved}\n")

        return rendered, resolved


class HorizontalLine(NamedTuple):
    """
    A path line element that takes its ordinate from the end of the previous element.

    See: `PaintedPath.horizontal_line_to`
    """

    x: Number
    """The abscissa of the horizontal line's end point."""

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is the resolved
            `Line`.
        """
        # pylint: disable=unused-argument
        end_point = Point(x=self.x, y=last_item.end_point.y)
        return _render_line(end_point), Line(end_point)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `HorizontalLine.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {resolved}\n")

        return rendered, resolved


class RelativeHorizontalLine(NamedTuple):
    """
    A path line element that takes its ordinate from the end of the previous element and
    computes its abscissa offset from the end of that element.

    See: `PaintedPath.horizontal_line_relative`
    """

    x: Number
    """
    The abscissa of the horizontal line's end point relative to the abscissa of the
    previous path element.
    """

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is the resolved
            `Line`.
        """
        # pylint: disable=unused-argument
        end_point = Point(x=last_item.end_point.x + self.x, y=last_item.end_point.y)
        return _render_line(end_point), Line(end_point)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `RelativeHorizontalLine.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {resolved}\n")

        return rendered, resolved


class VerticalLine(NamedTuple):
    """
    A path line element that takes its abscissa from the end of the previous element.

    See: `PaintedPath.vertical_line_to`
    """

    y: Number
    """The ordinate of the vertical line's end point."""

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is the resolved
            `Line`.
        """
        # pylint: disable=unused-argument
        end_point = Point(x=last_item.end_point.x, y=self.y)
        return _render_line(end_point), Line(end_point)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `VerticalLine.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {resolved}\n")

        return rendered, resolved


class RelativeVerticalLine(NamedTuple):
    """
    A path line element that takes its abscissa from the end of the previous element and
    computes its ordinate offset from the end of that element.

    See: `PaintedPath.vertical_line_relative`
    """

    y: Number
    """
    The ordinate of the vertical line's end point relative to the ordinate of the
    previous path element.
    """

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is the resolved
            `Line`.
        """
        # pylint: disable=unused-argument
        end_point = Point(x=last_item.end_point.x, y=last_item.end_point.y + self.y)
        return _render_line(end_point), Line(end_point)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `RelativeVerticalLine.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {resolved}\n")

        return rendered, resolved


class BezierCurve(NamedTuple):
    """
    A cubic Bézier curve path element.

    This draws a Bézier curve parameterized by the end point of the previous path
    element, two off-curve control points, and an end point.

    See: `PaintedPath.curve_to`
    """

    c1: Point
    """The curve's first control point."""
    c2: Point
    """The curve's second control point."""
    end: Point
    """The curve's end point."""

    @property
    def end_point(self):
        """The end point of this path element."""
        return self.end

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is `self`
        """
        # pylint: disable=unused-argument
        return (_render_curve(self.c1, self.c2, self.end), self)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `BezierCurve.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(str(self) + "\n")

        return rendered, resolved


class RelativeBezierCurve(NamedTuple):
    """
    A cubic Bézier curve path element whose points are specified relative to the end
    point of the previous path element.

    See: `PaintedPath.curve_relative`
    """

    c1: Point
    """
    The curve's first control point relative to the end of the previous path element.
    """
    c2: Point
    """
    The curve's second control point relative to the end of the previous path element.
    """
    end: Point
    """The curve's end point relative to the end of the previous path element."""

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is the resolved
            `BezierCurve`.
        """
        # pylint: disable=unused-argument
        last_point = last_item.end_point

        c1 = last_point + self.c1
        c2 = last_point + self.c2
        end = last_point + self.end

        return (
            _render_curve(c1, c2, end),
            BezierCurve(c1=c1, c2=c2, end=end),
        )

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `RelativeBezierCurve.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {resolved}\n")

        return rendered, resolved


class QuadraticBezierCurve(NamedTuple):
    """
    A quadratic Bézier curve path element.

    This draws a Bézier curve parameterized by the end point of the previous path
    element, one off-curve control point, and an end point.

    See: `PaintedPath.quadratic_bezier_to`
    """

    ctrl: Point
    """The curve's control point."""
    end: Point
    """The curve's end point."""

    @property
    def end_point(self):
        """The end point of this path element."""
        return self.end

    def to_cubic_curve(self, start_point):
        ctrl = self.ctrl
        end = self.end

        ctrl1 = Point(
            x=start_point.x + 2 * (ctrl.x - start_point.x) / 3,
            y=start_point.y + 2 * (ctrl.y - start_point.y) / 3,
        )
        ctrl2 = Point(
            x=end.x + 2 * (ctrl.x - end.x) / 3,
            y=end.y + 2 * (ctrl.y - end.y) / 3,
        )

        return BezierCurve(ctrl1, ctrl2, end)

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is `self`.
        """
        # pylint: disable=unused-argument
        return (
            self.to_cubic_curve(last_item.end_point).render(
                path_gsds, style, last_item
            )[0],
            self,
        )

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `QuadraticBezierCurve.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(
            f"{self} resolved to {self.to_cubic_curve(last_item.end_point)}\n"
        )

        return rendered, resolved


class RelativeQuadraticBezierCurve(NamedTuple):
    """
    A quadratic Bézier curve path element whose points are specified relative to the end
    point of the previous path element.

    See: `PaintedPath.quadratic_bezier_relative`
    """

    ctrl: Point
    """The curve's control point relative to the end of the previous path element."""
    end: Point
    """The curve's end point relative to the end of the previous path element."""

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is the resolved
            `QuadraticBezierCurve`.
        """
        # pylint: disable=unused-argument
        last_point = last_item.end_point

        ctrl = last_point + self.ctrl
        end = last_point + self.end

        absolute = QuadraticBezierCurve(ctrl=ctrl, end=end)
        return absolute.render(path_gsds, style, last_item)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `RelativeQuadraticBezierCurve.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(
            f"{self} resolved to {resolved} "
            f"then to {resolved.to_cubic_curve(last_item.end_point)}\n"
        )

        return rendered, resolved


class Arc(NamedTuple):
    """
    An elliptical arc path element.

    The arc is drawn from the end of the current path element to its specified end point
    using a number of parameters to determine how it is constructed.

    See: `PaintedPath.arc_to`
    """

    radii: Point
    """
    The x- and y-radii of the arc. If `radii.x == radii.y` the arc will be circular.
    """
    rotation: Number
    """The rotation of the arc's major/minor axes relative to the coordinate frame."""
    large: bool
    """If True, sweep the arc over an angle greater than or equal to 180 degrees."""
    sweep: bool
    """If True, the arc is swept in the positive angular direction."""
    end: Point
    """The end point of the arc."""

    @staticmethod
    @force_nodocument
    def subdivde_sweep(sweep_angle):
        """
        A generator that subdivides a swept angle into segments no larger than a quarter
        turn.

        Any sweep that is larger than a quarter turn is subdivided into as many equally
        sized segments as necessary to prevent any individual segment from being larger
        than a quarter turn.

        This is used for approximating a circular curve segment using cubic Bézier
        curves. This computes the parameters used for the Bézier approximation up
        front, as well as the transform necessary to place the segment in the correct
        position.

        Args:
            sweep_angle (Number): the angle to subdivide.

        Yields:
            A tuple of (ctrl1, ctrl2, end) representing the control and end points of
            the cubic Bézier curve approximating the segment as a unit circle centered
            at the origin.
        """
        sweep_angle = abs(sweep_angle)
        sweep_left = sweep_angle

        quarterturn = math.pi / 2
        chunks = math.ceil(sweep_angle / quarterturn)

        sweep_segment = sweep_angle / chunks
        cos_t = math.cos(sweep_segment)
        sin_t = math.sin(sweep_segment)
        kappa = 4 / 3 * math.tan(sweep_segment / 4)

        ctrl1 = Point(1, kappa)
        ctrl2 = Point(cos_t + kappa * sin_t, sin_t - kappa * cos_t)
        end = Point(cos_t, sin_t)

        for _ in range(chunks):
            offset = sweep_angle - sweep_left

            transform = Transform.rotation(offset)
            yield ctrl1 @ transform, ctrl2 @ transform, end @ transform

            sweep_left -= sweep_segment

    def _approximate_arc(self, last_item):
        """
        Approximate this arc with a sequence of `BezierCurve`.

        Args:
            last_item: the previous path element (used for its end point)

        Returns:
            a list of `BezierCurve`.
        """
        radii = self.radii

        reverse = Transform.rotation(-self.rotation)
        forward = Transform.rotation(self.rotation)

        prime = ((last_item.end_point - self.end) * 0.5) @ reverse

        lam_da = (prime.x / radii.x) ** 2 + (prime.y / radii.y) ** 2

        if lam_da > 1:
            radii = Point(x=(lam_da ** 0.5) * radii.x, y=(lam_da ** 0.5) * radii.y)

        sign = (self.large != self.sweep) - (self.large == self.sweep)
        rxry2 = (radii.x * radii.y) ** 2
        rxpy2 = (radii.x * prime.y) ** 2
        rypx2 = (radii.y * prime.x) ** 2

        centerprime = (
            sign
            * math.sqrt(round(rxry2 - rxpy2 - rypx2, 8) / (rxpy2 + rypx2))
            * Point(
                x=radii.x * prime.y / radii.y,
                y=-radii.y * prime.x / radii.x,
            )
        )

        center = (centerprime @ forward) + ((last_item.end_point + self.end) * 0.5)

        arcstart = Point(
            x=(prime.x - centerprime.x) / radii.x,
            y=(prime.y - centerprime.y) / radii.y,
        )
        arcend = Point(
            x=(-prime.x - centerprime.x) / radii.x,
            y=(-prime.y - centerprime.y) / radii.y,
        )

        theta = Point(1, 0).angle(arcstart)
        deltatheta = arcstart.angle(arcend)

        if (self.sweep is False) and (deltatheta > 0):
            deltatheta -= math.tau
        elif (self.sweep is True) and (deltatheta < 0):
            deltatheta += math.tau

        sweep_sign = (deltatheta >= 0) - (deltatheta < 0)
        final_tf = (
            Transform.scaling(x=1, y=sweep_sign)  # flip negative sweeps
            .rotate(theta)  # rotate start of arc to correct position
            .scale(radii.x, radii.y)  # scale unit circle into the final ellipse shape
            .rotate(self.rotation)  # rotate the ellipse the specified angle
            .translate(center.x, center.y)  # translate to the final coordinates
        )

        curves = []

        for ctrl1, ctrl2, end in self.subdivde_sweep(deltatheta):
            curves.append(
                BezierCurve(ctrl1 @ final_tf, ctrl2 @ final_tf, end @ final_tf)
            )

        return curves

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is a resolved
            `BezierCurve`.
        """
        # pylint: disable=unused-argument
        curves = self._approximate_arc(last_item)

        if not curves:
            return "", last_item

        return (
            " ".join(
                curve.render(path_gsds, style, prev)[0]
                for prev, curve in zip([last_item, *curves[:-1]], curves)
            ),
            curves[-1],
        )

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `Arc.render`.
        """
        # pylint: disable=unused-argument
        curves = self._approximate_arc(last_item)

        debug_stream.write(f"{self} resolved to:\n")
        if not curves:
            debug_stream.write(pfx + " └─ nothing\n")
            return "", last_item

        previous = [last_item]
        for curve in curves[:-1]:
            previous.append(curve)
            debug_stream.write(pfx + f" ├─ {curve}\n")
        debug_stream.write(pfx + f" └─ {curves[-1]}\n")

        return (
            " ".join(
                curve.render(path_gsds, style, prev)[0]
                for prev, curve in zip(previous, curves)
            ),
            curves[-1],
        )


class RelativeArc(NamedTuple):
    """
    An elliptical arc path element.

    The arc is drawn from the end of the current path element to its specified end point
    using a number of parameters to determine how it is constructed.

    See: `PaintedPath.arc_relative`
    """

    radii: Point
    """
    The x- and y-radii of the arc. If `radii.x == radii.y` the arc will be circular.
    """
    rotation: Number
    """The rotation of the arc's major/minor axes relative to the coordinate frame."""
    large: bool
    """If True, sweep the arc over an angle greater than or equal to 180 degrees."""
    sweep: bool
    """If True, the arc is swept in the positive angular direction."""
    end: Point
    """The end point of the arc relative to the end of the previous path element."""

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is a resolved
            `BezierCurve`.
        """
        # pylint: disable=unused-argument
        return Arc(
            self.radii,
            self.rotation,
            self.large,
            self.sweep,
            last_item.end_point + self.end,
        ).render(path_gsds, style, last_item)

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `RelativeArc.render`.
        """
        # pylint: disable=unused-argument
        # newline is intentionally missing here
        debug_stream.write(f"{self} resolved to ")

        return Arc(
            self.radii,
            self.rotation,
            self.large,
            self.sweep,
            last_item.end_point + self.end,
        ).render_debug(path_gsds, style, last_item, debug_stream, pfx)


class Rectangle(NamedTuple):
    """A pdf primitive rectangle."""

    org: Point
    """The top-left corner of the rectangle."""
    size: Point
    """The width and height of the rectangle."""

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is a `Line` back to
            the rectangle's origin.
        """
        # pylint: disable=unused-argument

        return (f"{self.org.render()} {self.size.render()} re", Line(self.org))

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `Rectangle.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {rendered}\n")

        return rendered, resolved


class ImplicitClose(NamedTuple):
    """
    A path close element that is conditionally rendered depending on the value of
    `GraphicsStyle.auto_close`.
    """

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is whatever the old
            last_item was.
        """
        # pylint: disable=unused-argument,no-self-use
        if style.auto_close:
            return "h", last_item

        return "", last_item

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `ImplicitClose.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(f"{self} resolved to {rendered}\n")

        return rendered, resolved


class Close(NamedTuple):
    """
    A path close element.

    Instructs the renderer to draw a straight line from the end of the last path element
    to the start of the current path.

    See: `PaintedPath.close`
    """

    @force_nodocument
    def render(self, path_gsds, style, last_item):
        """
        Render this path element to its PDF representation.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.

        Returns:
            a tuple of `(str, new_last_item)`, where `new_last_item` is whatever the old
            last_item was.
        """
        # pylint: disable=unused-argument,no-self-use
        return "h", last_item

    @force_nodocument
    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `Close.render`.
        """
        # pylint: disable=unused-argument
        rendered, resolved = self.render(path_gsds, style, last_item)
        debug_stream.write(str(self) + "\n")

        return rendered, resolved


class DrawingContext:
    """
    Base context for a drawing in a PDF

    This context is not stylable and is mainly responsible for transforming path
    drawing coordinates into user coordinates (i.e. it ensures that the output drawing
    is correctly scaled).
    """

    def __init__(self):
        self._subitems = []

    def add_item(self, item):
        """
        Append an item to this drawing context

        Args:
            item (GraphicsContext, PaintedPath): the item to be appended.
        """

        if not isinstance(item, (GraphicsContext, PaintedPath)):
            raise TypeError(f"{item} doesn't belong in a DrawingContext")

        self._subitems.append(item)

    @staticmethod
    def _setup_render_prereqs(first_point, scale, height):
        style = GraphicsStyle()
        style.auto_close = True
        style.paint_rule = PathPaintRule.AUTO
        style.intersection_rule = IntersectionRule.NONZERO

        last_item = Move(first_point)
        scale, last_item = (
            Transform.scaling(x=1, y=-1)
            .about(x=0, y=height / 2)
            .scale(scale)
            .render(last_item)
        )

        # we use an OrderedDict here so that the path_gsds output ordering is
        # deterministic for a given input and also inherently deduplicated.
        path_gsds = OrderedDict()
        render_list = ["q", scale]

        return render_list, path_gsds, style, last_item

    def render(self, first_point, scale, height):
        """
        Render the drawing context to PDF format.

        Args:
            first_point (Point): the starting point to use if the first path element is
                a relative element.
            scale (Number): the scale factor to convert from PDF pt units into the
                document's semantic units (e.g. mm or in).
            height (Number): the page height. This is used to remap the coordinates to
                be from the top-left corner of the page (matching fpdf's behavior)
                instead of the PDF native behavior of bottom-left.

        Returns:
            A `tuple[str, dict[str, None]]` where the string is the PDF representation
            of all the paths and groups in this context, and the dict's keys are the
            names of the graphics state dictionaries used in this context so that they
            can be retrieved later using `get_style_dict_by_name`.
        """
        if not self._subitems:
            return "", OrderedDict()

        render_list, path_gsds, style, last_item = self._setup_render_prereqs(
            first_point, scale, height
        )

        for item in self._subitems:
            rendered, last_item = item.render(path_gsds, style, last_item)
            if rendered:
                render_list.append(rendered)

        render_list.append("Q")

        return " ".join(render_list), path_gsds

    def render_debug(self, first_point, scale, height, debug_stream):
        render_list, path_gsds, style, last_item = self._setup_render_prereqs(
            first_point, scale, height
        )

        debug_stream.write("ROOT\n")
        for child in self._subitems[:-1]:
            debug_stream.write(" ├─ ")
            rendered = child.render_debug(
                path_gsds, style, last_item, debug_stream, " │  "
            )
            if rendered:
                render_list.append(rendered)

        if self._subitems:
            debug_stream.write(" └─ ")
            rendered, last_item = self._subitems[-1].render_debug(
                path_gsds, style, last_item, debug_stream, "    "
            )
            if rendered:
                render_list.append(rendered)

            render_list.append("Q")

            # print(render_list)
            return " ".join(render_list), path_gsds

        return "", OrderedDict()


class PaintedPath:
    """
    A path to be drawn by the PDF renderer.

    A painted path is defined by a style and an arbitrary sequence of path elements,
    which include the primitive path elements (`Move`, `Line`, `BezierCurve`, ...) as
    well as arbitrarily nested `GraphicsContext` containing their own sequence of
    primitive path elements and `GraphicsContext`.
    """

    def __init__(self, x=0, y=0):
        self._root_graphics_context = GraphicsContext()
        self._graphics_context = self._root_graphics_context

        self._closed = True
        self._close_context = self._graphics_context

        self.move_to(x, y)

    @property
    def style(self):
        """The `GraphicsStyle` applied to all elements of this path."""
        return self._root_graphics_context.style

    @property
    def transform(self):
        """The `Transform` that applies to all of the elements of this path."""
        return self._root_graphics_context.transform

    @transform.setter
    def transform(self, tf):
        self._root_graphics_context.transform = tf

    @property
    def auto_close(self):
        """If true, the path should automatically close itself before painting."""
        return self.style.auto_close

    @auto_close.setter
    def auto_close(self, should):
        self.style.auto_close = should

    @property
    def paint_rule(self):
        """Manually specify the `PathPaintRule` to use for rendering the path."""
        return self.style.paint_rule

    @paint_rule.setter
    def paint_rule(self, style):
        self.style.paint_rule = style

    @property
    def clipping_path(self):
        """Set the clipping path for this path."""
        return self._root_graphics_context.clipping_path

    @clipping_path.setter
    def clipping_path(self, new_clipath):
        self._root_graphics_context.clipping_path = new_clipath

    @contextmanager
    def _new_graphics_context(self, _attach=True):
        old_graphics_context = self._graphics_context
        new_graphics_context = GraphicsContext()
        self._graphics_context = new_graphics_context
        try:
            yield new_graphics_context
            if _attach:
                old_graphics_context.add_item(new_graphics_context)
        finally:
            self._graphics_context = old_graphics_context

    @contextmanager
    def transform_group(self, transform):
        """
        Apply the provided `Transform` to all points added within this context.
        """
        with self._new_graphics_context() as ctxt:
            ctxt.transform = transform
            yield self

    def add_path_element(self, item):
        """
        Add the given element as a path item of this path.
        """
        if self._starter_move is not None:
            self._closed = False

            self._graphics_context.add_item(self._starter_move)
            self._close_context = self._graphics_context
            self._starter_move = None

        self._graphics_context.add_item(item)

    def rectangle(self, x, y, w, h, rx=0, ry=0):
        """
        Append a rectangle as a closed subpath to the current path.
        """

        if (rx == 0) or (ry == 0):
            self._insert_implicit_close_if_open()
            self.add_path_element(Rectangle(Point(x, y), Point(w, h)))
        else:
            rx = abs(rx)
            ry = abs(ry)
            self.move_to(x + rx, y)
            self.line_to(x + w - rx, y)
            self.arc_to(rx, ry, 0, False, True, x + w, y + ry)
            self.line_to(x + w, y + h - ry)
            self.arc_to(rx, ry, 0, False, True, x + w - rx, y + h)
            self.line_to(x + rx, y + h)
            self.arc_to(rx, ry, 0, False, True, x, y + h - ry)
            self.line_to(x, y + ry)
            self.arc_to(rx, ry, 0, False, True, x + rx, y)
            self.close()

        return self

    def circle(self, cx, cy, r):
        """
        Append a circle as a closed subpath to the current path.

        Args:
            cx (Number): the abscissa of the circle's center point.
            cy (Number): the ordinate of the circle's center point.
            r (Number): the radius of the circle.

        Returns:
            The path, to allow chaining method calls.
        """
        return self.ellipse(cx, cy, r, r)

    def ellipse(self, cx, cy, rx, ry):
        """
        Append an ellipse as a closed subpath to the current path.

        Args:
            cx (Number): the abscissa of the ellipse's center point.
            cy (Number): the ordinate of the ellipse's center point.
            rx (Number): the x-radius of the ellipse.
            ry (Number): the y-radius of the ellipse.

        Returns:
            The path, to allow chaining method calls.
        """
        rx = abs(rx)
        ry = abs(ry)

        # this isn't the most efficient way to do this, computationally, but it's
        # internally consistent.
        self.move_to(cx + rx, cy)
        self.arc_to(rx, ry, 0, False, True, cx, cy + ry)
        self.arc_to(rx, ry, 0, False, True, cx - rx, cy)
        self.arc_to(rx, ry, 0, False, True, cx, cy - ry)
        self.arc_to(rx, ry, 0, False, True, cx + rx, cy)
        self.close()

        return self

    def move_to(self, x, y):
        """
        Start a new subpath or move the path starting point.

        If no path elements have been added yet, this will change the path starting
        point. If path elements have been added, this will insert an implicit close in
        order to start a new subpath.

        Args:
            x (Number): abscissa of the (sub)path starting point.
            y (Number): ordinate of the (sub)path starting point.

        Returns:
            The path, to allow chaining method calls.

        """
        self._insert_implicit_close_if_open()
        self._starter_move = Move(Point(x, y))
        return self

    def move_relative(self, x, y):
        """
        Start a new subpath or move the path start point relative to the previous point.

        If no path elements have been added yet, this will change the path starting
        point. If path elements have been added, this will insert an implicit close in
        order to start a new subpath.

        This will overwrite an absolute move_to as long as no non-move path items have
        been appended. The relative position is resolved from the previous item when
        the path is being rendered, or from 0, 0 if it is the first item.

        Args:
            x (Number): abscissa of the (sub)path starting point relative to the.
            y (Number): ordinate of the (sub)path starting point relative to the.
        """

        self._insert_implicit_close_if_open()
        self._starter_move = RelativeMove(Point(x, y))
        return self

    def line_to(self, x, y):
        """
        Append a straight line to this path.

        Args:
            x (Number): abscissa the line's end point.
            y (Number): ordinate of the line's end point.

        Returns:
            The path, to allow chaining method calls.
        """
        self.add_path_element(Line(Point(x, y)))
        return self

    def line_relative(self, dx, dy):
        """
        Append a straight line whose end is computed as an offset from the end of the
        previous path element.

        Args:
            x (Number): abscissa the line's end point relative to the end point of the
                previous path element.
            y (Number): ordinate of the line's end point relative to the end point of
                the previous path element.

        Returns:
            The path, to allow chaining method calls.
        """
        self.add_path_element(RelativeLine(Point(dx, dy)))
        return self

    def horizontal_line_to(self, x):
        """
        Append a straight horizontal line to the given abscissa. The ordinate is
        retrieved from the end point of the previous path element.

        Args:
            x (Number): abscissa of the line's end point.

        Returns:
            The path, to allow chaining method calls.
        """
        self.add_path_element(HorizontalLine(x))
        return self

    def horizontal_line_relative(self, dx):
        """
        Append a straight horizontal line to the given offset from the previous path
        element. The ordinate is retrieved from the end point of the previous path
        element.

        Args:
            x (Number): abscissa of the line's end point relative to the end point of
                the previous path element.

        Returns:
            The path, to allow chaining method calls.
        """
        self.add_path_element(RelativeHorizontalLine(dx))
        return self

    def vertical_line_to(self, y):
        """
        Append a straight vertical line to the given ordinate. The abscissa is
        retrieved from the end point of the previous path element.

        Args:
            y (Number): ordinate of the line's end point.

        Returns:
            The path, to allow chaining method calls.
        """
        self.add_path_element(VerticalLine(y))
        return self

    def vertical_line_relative(self, dy):
        """
        Append a straight vertical line to the given offset from the previous path
        element. The abscissa is retrieved from the end point of the previous path
        element.

        Args:
            y (Number): ordinate of the line's end point relative to the end point of
                the previous path element.

        Returns:
            The path, to allow chaining method calls.
        """
        self.add_path_element(RelativeVerticalLine(dy))
        return self

    def curve_to(self, x1, y1, x2, y2, x3, y3):
        """
        Append a cubic Bézier curve to this path.

        Args:
            x1 (Number): abscissa of the first control point
            y1 (Number): ordinate of the first control point
            x2 (Number): abscissa of the second control point
            y2 (Number): ordinate of the second control point
            x3 (Number): abscissa of the end point
            y3 (Number): ordinate of the end point

        Returns:
            The path, to allow chaining method calls.
        """
        ctrl1 = Point(x1, y1)
        ctrl2 = Point(x2, y2)
        end = Point(x3, y3)

        self.add_path_element(BezierCurve(ctrl1, ctrl2, end))
        return self

    def curve_relative(self, dx1, dy1, dx2, dy2, dx3, dy3):
        """
        Append a cubic Bézier curve whose points are expressed relative to the
        end point of the previous path element.

        E.g. with a start point of (0, 0), given (1, 1), (2, 2), (3, 3), the output
        curve would have the points:

        (0, 0) c1 (1, 1) c2 (3, 3) e (6, 6)

        Args:
            dx1 (Number): abscissa of the first control point relative to the end point
                of the previous path element
            dy1 (Number): ordinate of the first control point relative to the end point
                of the previous path element
            dx2 (Number): abscissa offset of the second control point relative to the
                first control point
            dy2 (Number): ordinate offset of the second control point relative to the
                first control point
            dx3 (Number): abscissa offset of the end point relative to the second
                control point
            dy3 (Number): ordinate offset of the end point relative to the second
                control point

        Returns:
            The path, to allow chaining method calls.
        """
        c1d = Point(dx1, dy1)
        c2d = Point(dx2, dy2)
        end = Point(dx3, dy3)

        self.add_path_element(RelativeBezierCurve(c1d, c2d, end))
        return self

    def quadratic_bezier_to(self, x1, y1, x2, y2):
        """
        Append a cubic Bézier curve mimicking the specified quadratic Bézier curve.
        """
        ctrl = Point(x1, y1)
        end = Point(x2, y2)
        self.add_path_element(QuadraticBezierCurve(ctrl, end))
        return self

    def quadratic_bezier_relative(self, x1, y1, x2, y2):
        """
        Append a cubic Bézier curve mimicking the specified quadratic Bézier curve.
        """
        ctrl = Point(x1, y1)
        end = Point(x2, y2)
        self.add_path_element(RelativeQuadraticBezierCurve(ctrl, end))
        return self

    def arc_to(self, rx, ry, rotation, large_arc, positive_sweep, x, y):
        """
        Append an elliptical arc from the end of the previous path point to the
        specified end point.

        The arc is approximated using Bézier curves, so it is not perfectly accurate.
        However, the error is small enough to not be noticeable at any reasonable
        (and even most unreasonable) scales, with a worst-case deviation of around 3‱.

        Notes:
            - The signs of the radii arguments (`rx` and `ry`) are ignored (i.e. their
              absolute values are used instead).
            - If either radius is 0, then a straight line will be emitted instead of an
              arc.
            - If the radii are too small for the arc to reach from the current point to
              the specified end point (`x` and `y`), then they will be proportionally
              scaled up until they are big enough, which will always result in a
              half-ellipse arc (i.e. an 180 degree sweep)

        Args:
            rx (Number): radius in the x-direction.
            ry (Number): radius in the y-direction.
            rotation (Number): angle (in degrees) that the arc should be rotated
                clockwise from the principle axes. This parameter does not have
                a visual effect in the case that `rx == ry`.
            large_arc (bool): if True, the arc will cover a sweep angle of at least 180
                degrees. Otherwise, the sweep angle will be at most 180 degrees.
            positive_sweep (bool): if True, the arc will be swept over a positive angle,
                i.e. clockwise. Otherwise, the arc will be swept over a negative
                angle.
            x (Number): abscissa of the arc's end point.
            y (Number): ordinate of the arc's end point.
        """

        if rx == 0 or ry == 0:
            return self.line_to(x, y)

        radii = Point(abs(rx), abs(ry))
        large_arc = bool(large_arc)
        rotation = math.radians(rotation)
        positive_sweep = bool(positive_sweep)
        end = Point(x, y)

        self.add_path_element(Arc(radii, rotation, large_arc, positive_sweep, end))
        return self

    def arc_relative(self, rx, ry, rotation, large_arc, positive_sweep, dx, dy):
        """
        Append an elliptical arc from the end of the previous path point to an offset
        point.

        The arc is approximated using Bézier curves, so it is not perfectly accurate.
        However, the error is small enough to not be noticeable at any reasonable
        (and even most unreasonable) scales, with a worst-case deviation of around 3‱.

        Notes:
            - The signs of the radii arguments (`rx` and `ry`) are ignored (i.e. their
              absolute values are used instead).
            - If either radius is 0, then a straight line will be emitted instead of an
              arc.
            - If the radii are too small for the arc to reach from the current point to
              the specified end point (`x` and `y`), then they will be proportionally
              scaled up until they are big enough, which will always result in a
              half-ellipse arc (i.e. an 180 degree sweep)

        Args:
            rx (Number): radius in the x-direction.
            ry (Number): radius in the y-direction.
            rotation (Number): angle (in degrees) that the arc should be rotated
                clockwise from the principle axes. This parameter does not have
                a visual effect in the case that `rx == ry`.
            large_arc (bool): if True, the arc will cover a sweep angle of at least 180
                degrees. Otherwise, the sweep angle will be at most 180 degrees.
            positive_sweep (bool): if True, the arc will be swept over a positive angle,
                i.e. clockwise. Otherwise, the arc will be swept over a negative
                angle.
            dx (Number): abscissa of the arc's end point relative to the end point of
                the previous path element.
            dy (Number): ordinate of the arc's end point relative to the end point of
                the previous path element.
        """
        if rx == 0 or ry == 0:
            return self.line_relative(dx, dy)

        radii = Point(abs(rx), abs(ry))
        large_arc = bool(large_arc)
        rotation = math.radians(rotation)
        positive_sweep = bool(positive_sweep)
        end = Point(dx, dy)

        self.add_path_element(
            RelativeArc(radii, rotation, large_arc, positive_sweep, end)
        )
        return self

    def close(self):
        """
        Explicitly close the current (sub)path.
        """
        self.add_path_element(Close())
        self._closed = True
        self.move_relative(0, 0)

    def _insert_implicit_close_if_open(self):
        if not self._closed:
            self._close_context.add_item(ImplicitClose())
            self._close_context = self._graphics_context
            self._closed = True

    def render(self, path_gsds, style, last_item, debug_stream=None, pfx=None):
        self._insert_implicit_close_if_open()

        render_list, last_item = self._root_graphics_context.build_render_list(
            path_gsds, style, last_item, debug_stream, pfx
        )

        paint_rule = GraphicsStyle.merge(style, self.style).resolve_paint_rule()

        render_list.insert(-1, paint_rule.value)

        return " ".join(render_list), last_item

    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `PaintedPath.render`.
        """
        return self.render(path_gsds, style, last_item, debug_stream, pfx)


class ClippingPath(PaintedPath):
    """
    The PaintedPath API but to be used to create clipping paths.

    .. warning::
        Unless you really know what you're doing, changing attributes of the clipping
        path style is likely to produce unexpected results. This is because the
        clipping path styles override implicit style inheritance of the `PaintedPath`
        it applies to.

        For example, `clippath.style.stroke_width = 2` can unexpectedly override
        `paintpath.style.stroke_width = GraphicsStyle.INHERIT` and cause the painted
        path to be rendered with a stroke of 2 instead of what it would have normally
        inherited. Because a `ClippingPath` can be painted like a normal `PaintedPath`,
        it would be overly restrictive to remove the ability to style it, so instead
        this warning is here.
    """

    # because clipping paths can be painted, we inherit from PaintedPath. However, when
    # setting the styling on the clipping path, those values will also be applied to
    # the PaintedPath the ClippingPath is applied to unless they are explicitly set for
    # that painted path. This is not ideal, but there's no way to really fix it from
    # the PDF rendering model, and trying to track the appropriate state/defaults seems
    # similarly error prone.

    # In general, the expectation is that painted clipping paths are likely to be very
    # uncommon, so it's an edge case that isn't worth worrying too much about.

    def __init__(self, x=0, y=0):
        super().__init__(x=x, y=y)
        self.paint_rule = PathPaintRule.DONT_PAINT

    # def __deepcopy__(self, memo):
    #     copied = ClippingPath(self._intersection_rule, self._paint_style)
    #     copied._root_graphics_context = copy.deepcopy(self._root_graphics_context, memo)
    #     copied._graphics_context = copied._root_graphics_context
    #     copied._closed = self._closed
    #     return copied

    def render(self, path_gsds, style, last_item, debug_stream=None, pfx=None):
        # painting the clipping path outside of its root graphics context allows it to
        # be transformed without affecting the transform of the graphics context of the
        # path it is being used to clip. This is because, unlike all of the other style
        # settings, transformations immediately affect the points following them,
        # rather than only affecting them at painting time. stroke settings and color
        # settings are applied only at paint time.

        if debug_stream:
            debug_stream.write("<ClippingPath> ")

        render_list, last_item = self._root_graphics_context.build_render_list(
            path_gsds, style, last_item, debug_stream, pfx, _push_stack=False
        )

        merged_style = GraphicsStyle.merge(style, self.style)
        # we should never get a collision error here
        intersection_rule = merged_style.intersection_rule
        if merged_style.intersection_rule == GraphicsStyle.INHERIT:
            intersection_rule = ClippingPathIntersectionRule.NONZERO
        else:
            intersection_rule = ClippingPathIntersectionRule[intersection_rule.name]

        paint_rule = merged_style.resolve_paint_rule()

        if debug_stream:
            ...

        render_list.append(intersection_rule.value)
        render_list.append(paint_rule.value)

        return " ".join(render_list), last_item

    def render_debug(self, path_gsds, style, last_item, debug_stream, pfx):
        """
        Render this path element to its PDF representation and produce debug
        information.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).

        Returns:
            The same tuple as `ClippingPath.render`.
        """
        return self.render(path_gsds, style, last_item, debug_stream, pfx)


class GraphicsContext:
    def __init__(self):
        self.style = GraphicsStyle()
        self.path_items = []

        self._transform = None
        self._clipping_path = None

    @property
    def transform(self):
        return self._transform

    @transform.setter
    def transform(self, tf):
        self._transform = tf

    # def __deepcopy__(self, memo):
    #     copied = GraphicsContext()
    #     copied._style_items = copy.deepcopy(self._style_items, memo)
    #     copied.path_items = copy.deepcopy(self.path_items, memo)
    #     return copied

    @property
    def clipping_path(self):
        """The `ClippingPath` for this graphics context."""
        return self._clipping_path

    @clipping_path.setter
    def clipping_path(self, new_clipath):
        self._clipping_path = new_clipath

    def add_item(self, item):
        """
        Add a path element to this graphics context.

        Args:
            item: the path element to add. May be a primitive element or another
                `GraphicsContext` or a `PaintedPath`.
        """
        self.path_items.append(item)

    def merge(self, other_context):
        """Copy another `GraphicsContext`'s path items into this one."""
        self.path_items.extend(other_context.path_items)

    @force_nodocument
    def build_render_list(
        self, path_gsds, style, last_item, debug_stream=None, pfx=None, _push_stack=True
    ):
        """
        Build a list composed of all all the individual elements rendered.

        This is used by `PaintedPath` and `ClippingPath` to reuse the `GraphicsContext`
        rendering process while still being able to inject some path specific items
        (e.g. the painting directive) before the render is collapsed into a single
        string.

        Args:
            path_gsds (dict): a dict of all graphics state dictionaries generated
                during rendering up to this point.
            style (GraphicsStyle): the current resolved graphics style
            last_item: the previous path element.
            debug_stream (io.TextIO): the stream to which the debug output should be
                written. This is not guaranteed to be seekable (e.g. it may be stdout or
                stderr).
            pfx (str): the current debug output prefix string (only needed if emitting
                more than one line).
            _push_stack (bool): if True, wrap the resulting render list in a push/pop
                graphics stack directive pair.

        Returns:
            `tuple[list[str], last_item]` where `last_item` is the past path element in
            this `GraphicsContext`
        """
        render_list = []

        if self.path_items:
            if debug_stream is not None:
                debug_stream.write(f"{self.__class__.__name__}")

            merged_style = GraphicsStyle.merge(style, self.style)

            if debug_stream is not None:
                styles_dbg = []
                for attr in GraphicsStyle.MERGE_PROPERTIES:
                    val = getattr(merged_style, attr)
                    if val is not GraphicsStyle.INHERIT:
                        if getattr(self.style, attr) is GraphicsStyle.INHERIT:
                            inh = " (inherited)"
                        else:
                            inh = ""

                        styles_dbg.append(f"{attr}: {val}{inh}")

                if styles_dbg:
                    debug_stream.write(" {\n")
                    for style_dbg_line in styles_dbg:
                        debug_stream.write(pfx + "    ")
                        debug_stream.write(style_dbg_line)
                        debug_stream.write("\n")

                    debug_stream.write(pfx + "}┐\n")
                else:
                    debug_stream.write("\n")

            sdict = _get_or_set_style_dict(self.style)

            if sdict is not None:
                path_gsds[sdict] = None
                render_list.append(f"{render_pdf_primitive(sdict)} gs")

            NO_EMIT_SET = {None, GraphicsStyle.INHERIT}
            # we can't set color in the graphics state context dictionary, so we have to
            # manually inherit it and emit it here.
            fill_color = self.style.fill_color
            stroke_color = self.style.stroke_color
            dash_pattern = self.style.stroke_dash_pattern

            if fill_color not in NO_EMIT_SET:
                render_list.append(
                    " ".join(number_to_str(val) for val in fill_color.colors)
                    + f" {fill_color.OPERATOR.lower()}"
                )

            if stroke_color not in NO_EMIT_SET:
                render_list.append(
                    " ".join(number_to_str(val) for val in stroke_color.colors)
                    + f" {stroke_color.OPERATOR.upper()}"
                )

            # We perform this redundant drawing operation here (the dash pattern is also
            # emitted to the graphics state parameter dictionary for this path) because
            # macOS preview.app does not appear to render dash patterns specified in
            # the graphics state parameter dictionary. This was cross-referenced
            # against mupdf and adobe acrobat reader DC, which both do render as
            # expected, giving some assurance that it isn't a problem with the PDF
            # generation itself.
            if dash_pattern not in NO_EMIT_SET:
                render_list.append(
                    render_pdf_primitive(dash_pattern)
                    + f" {number_to_str(self.style.stroke_dash_phase)} d"
                )

            if debug_stream:
                if self.clipping_path is not None:
                    debug_stream.write(pfx + " ├─ ")
                    rendered_cpath, _ = self.clipping_path.render_debug(
                        path_gsds, merged_style, last_item, debug_stream, pfx + " │  "
                    )
                    if rendered_cpath:
                        render_list.append(rendered_cpath)

                for item in self.path_items[:-1]:
                    debug_stream.write(pfx + " ├─ ")
                    rendered, last_item = item.render_debug(
                        path_gsds, merged_style, last_item, debug_stream, pfx + " │  "
                    )

                    if rendered:
                        render_list.append(rendered)

                debug_stream.write(pfx + " └─ ")
                rendered, last_item = self.path_items[-1].render_debug(
                    path_gsds, merged_style, last_item, debug_stream, pfx + "    "
                )

                if rendered:
                    render_list.append(rendered)

            else:
                if self.clipping_path is not None:
                    rendered_cpath, _ = self.clipping_path.render(
                        path_gsds, merged_style, last_item
                    )
                    if rendered_cpath:
                        render_list.append(rendered_cpath)

                for item in self.path_items:
                    rendered, last_item = item.render(
                        path_gsds, merged_style, last_item
                    )

                    if rendered:
                        render_list.append(rendered)

            # insert transform before points
            if self.transform is not None:
                render_list.insert(0, self.transform.render(last_item)[0])

            if _push_stack:
                render_list.insert(0, "q")
                render_list.append("Q")

        return render_list, last_item

    def render(
        self, path_gsds, style, last_item, debug_stream=None, pfx=None, _push_stack=True
    ):
        render_list, last_item = self.build_render_list(
            path_gsds, style, last_item, debug_stream, pfx, _push_stack=_push_stack
        )

        return " ".join(render_list), last_item

    def render_debug(
        self, path_gsds, style, last_item, debug_stream, pfx, _push_stack=True
    ):
        return self.render(
            path_gsds, style, last_item, debug_stream, pfx, _push_stack=_push_stack
        )