"""Run credential-free regression suites for the 985 migration."""
import inspect
import unittest


def main():
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.discover('.', pattern='test*.py')
    )
    if not result.wasSuccessful():
        return 1
    import test_stats_reporter
    import test_analytics_sheets
    count = 0
    for module in (test_stats_reporter, test_analytics_sheets):
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if name.startswith('test_') and not inspect.signature(function).parameters:
                function()
                count += 1
    print(f'Function assertions passed: {count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
