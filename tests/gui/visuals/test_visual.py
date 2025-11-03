from app.gui.visuals.visual import MarqueeBoxVisual


class TestMarqueeBoxVisual:
    def test_size_and_bbox(self):
        m = MarqueeBoxVisual((10, 20, 30, 50))
        assert m.size == (20, 30)
        assert m.bbox == (10, 20, 30, 50)

    def test_intersects_true_and_false(self):
        a = MarqueeBoxVisual((0, 0, 100, 100))
        b = MarqueeBoxVisual((50, 50, 150, 150))
        c = MarqueeBoxVisual((110, 110, 200, 200))
        assert a.intersects(b) and b.intersects(a)
        assert not a.intersects(c)
        assert not c.intersects(a)
