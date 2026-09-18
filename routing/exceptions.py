"""
Domain errors. Each carries the HTTP status and machine-readable code the API
should answer with, so views stay free of error-mapping logic.
"""


class RoutePlanningError(Exception):
    status_code = 500
    code = 'planning_error'

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class LocationNotFound(RoutePlanningError):
    """The start or finish could not be resolved to a point."""
    status_code = 400
    code = 'location_not_found'


class LocationOutsideUSA(RoutePlanningError):
    status_code = 400
    code = 'location_outside_usa'


class NoRouteFound(RoutePlanningError):
    """The routing engine knows of no drivable route (e.g. to Hawaii)."""
    status_code = 422
    code = 'no_route'


class NoFeasibleFuelPlan(RoutePlanningError):
    """Some stretch of the route has no station within the vehicle's range."""
    status_code = 422
    code = 'no_feasible_fuel_plan'


class UpstreamServiceError(RoutePlanningError):
    """The external routing/geocoding service failed or timed out."""
    status_code = 503
    code = 'upstream_unavailable'
