"""애플리케이션 도메인 예외 계층."""


class AppBaseError(Exception):
    """모든 애플리케이션 예외의 최상위."""


class ConfigError(AppBaseError):
    """설정 로딩·검증 실패."""


class DriverError(AppBaseError):
    """브라우저 제어·페이지 파싱 실패."""


class NotifyError(AppBaseError):
    """알림 전송 실패."""
