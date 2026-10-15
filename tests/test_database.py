from app.database import engine, Base, get_db


def test_base_metadata_exists():
    assert Base.metadata is not None


def test_get_db_is_generator():
    import inspect
    assert inspect.isgeneratorfunction(get_db)


def test_engine_created():
    assert engine is not None
    assert hasattr(engine, "connect")
