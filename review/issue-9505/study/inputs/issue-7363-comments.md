## wjones127 2026-07-01T22:05:18Z
https://github.com/lance-format/lance/issues/7363#issuecomment-4860401444

I tried this, but I found it's not as beneficial as I thought. DataFusion will repartition data across threads, and HashJoins will shuffle the order / partition of each row. This means that the rows arrive in sparse selections in Take, which leads to sub-optimal IO compared to simply scanning. Thus, in order for this to be worthwhile you you need to have substantially fewer rows in the Take than you would in the Scan. It might be more worthwhile to support better pushdown in the Scan itself, as suggested by https://github.com/lance-format/lance/issues/7562
