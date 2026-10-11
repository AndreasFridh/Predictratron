import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import ModelSpec
from app.engine import aggregate_periods, forecast, parse_csv, train
from app.home_assistant import HAClient, raw_frame, statistic_frame
from app.main import create_app
from app.store import Store


def weekly(**kwargs):
    return ModelSpec(name='Veckosnitt', source='csv', resolution='week', horizon=4,
                     target={'key':'level', 'statistic':'mean'},
                     inputs=[{'key':'rain','statistic':'sum'},{'key':'last','statistic':'last'}],
                     lags=[0,1,2], windows=[2,4], calendar=['week'], **kwargs)


@pytest.mark.parametrize('resolution,minutes', [('minute',1),('hour',60),('day',1440),('week',10080),('custom',90)])
def test_period_lengths_and_boundaries(resolution, minutes):
    spec=ModelSpec(name='Period',source='csv',target={'key':'value'},resolution=resolution,period_minutes=90)
    stamp=pd.Timestamp('2026-10-11T13:42:00Z')
    boundary=spec.floor(stamp)
    assert spec.step_minutes==minutes
    assert boundary<=stamp<boundary+pd.Timedelta(spec.freq)
    if resolution=='week':
        assert boundary.dayofweek==0 and boundary.hour==0
        assert boundary==pd.Timestamp('2026-10-05T00:00:00Z')


def test_weekly_hourly_csv_aggregates_mean_sum_last_without_future_data():
    spec=weekly()
    index=pd.date_range('2026-01-05T01:00:00Z',periods=336,freq='h')
    frame=pd.DataFrame({'level':np.arange(1,337),'rain':1,'last':np.arange(1,337)},index=index)
    frame.index.name='timestamp'
    result=parse_csv(frame.to_csv().encode(),spec,60)
    assert list(result.index)==[pd.Timestamp('2026-01-12T00:00:00Z'),pd.Timestamp('2026-01-19T00:00:00Z')]
    assert result.iloc[0].to_dict()=={'level':84.5,'rain':168.0,'last':168.0}
    incomplete=frame.copy()
    incomplete.loc[index[10],'level']=np.nan
    reduced=aggregate_periods(incomplete,spec,60)
    assert pd.isna(reduced.iloc[0]['level'])
    assert reduced.iloc[0]['rain']==168
    assert reduced.iloc[1]['level']==252.5


def test_csv_rejects_upsampling_and_misaligned_week_boundaries():
    spec=weekly()
    content=b'timestamp,level,rain,last\n2026-01-08T00:00:00Z,10,2,10\n'
    with pytest.raises(ValueError,match='gränserna'):
        parse_csv(content,spec)
    with pytest.raises(ValueError,match='Uppsampling'):
        parse_csv(content,spec,20160)
    with pytest.raises(ValueError,match='inga kompletta'):
        parse_csv(content,spec,1440)


def test_weekly_training_and_forecasting_uses_separate_complete_weeks():
    spec=weekly()
    end=spec.floor(pd.Timestamp.now(tz='UTC'))
    index=pd.date_range(end=end,periods=1820,freq='24h')
    t=np.arange(len(index))
    raw=pd.DataFrame({'level':40+np.sin(t/50),'rain':np.maximum(0,np.sin(t/7)),'last':40+np.sin(t/50)},index=index)
    frame=aggregate_periods(raw,spec,1440)
    artifact=train(frame,spec)
    result=forecast(frame,spec,artifact)
    assert len(result['points'])==4
    assert result['period_minutes']==10080
    assert result['points'][0]['start']==end.isoformat()
    assert result['points'][0]['end']==(end+pd.Timedelta(days=7)).isoformat()
    assert result['points'][-1]['end']==(end+pd.Timedelta(days=28)).isoformat()
    assert pd.Timestamp(artifact['metrics']['train_last_target'])<pd.Timestamp(artifact['metrics']['test_first_origin'])


def test_weekly_ha_statistics_preserve_mean_and_cumulative_increment():
    spec=ModelSpec(name='HA week',resolution='week',target={'key':'level','entity_id':'sensor.level'},
                   inputs=[{'key':'rain','entity_id':'sensor.rain','statistic':'change'}])
    index=pd.date_range('2026-01-05T01:00:00Z',periods=168,freq='h')
    data={key:[{'end':int(s.timestamp()*1000),'mean':10+i,'change':2} for i,s in enumerate(index)] for key in ['sensor.level','sensor.rain']}
    result=statistic_frame(data,spec,index[-1])
    assert result.iloc[0]['level']==93.5
    assert result.iloc[0]['rain']==336
    data['sensor.rain'].pop(12)
    result=statistic_frame(data,spec,index[-1])
    assert pd.isna(result.iloc[0]['rain'])


def test_fifteen_minute_ha_requests_five_minute_statistics():
    class FakeHA(HAClient):
        def websocket(self,command):
            self.command=command
            end=pd.Timestamp.now(tz='UTC').floor('15min')
            return {'sensor.level':[{'end':int((end-pd.Timedelta(minutes=i)).timestamp()*1000),'mean':3} for i in [10,5,0]]}
    spec=ModelSpec(name='15 min',resolution='custom',period_minutes=15,target={'key':'level','entity_id':'sensor.level'})
    ha=FakeHA(url='',token='')
    result=ha.history(spec)
    assert ha.command['period']=='5minute'
    assert result.iloc[-1]['level']==3
    with pytest.raises(ValidationError,match='fem minuter'):
        ModelSpec(name='1 min',resolution='minute',target={'key':'rain','entity_id':'sensor.rain','statistic':'change'})


def test_weekly_raw_history_time_weighting_uses_monday_anchor():
    spec=weekly()
    start=pd.Timestamp('2026-01-05T00:00:00Z')
    end=start+pd.Timedelta(days=7)
    records=[{'last_changed':start.isoformat(),'state':'2'},{'last_changed':(start+pd.Timedelta(days=3)).isoformat(),'state':'9'}]
    result=raw_frame(records,spec.target,start,end,spec.freq,spec.anchor)
    assert result.iloc[0]==6
    assert result.index[0]==end


def test_custom_interval_change_protects_existing_history(tmp_path):
    store=Store(tmp_path)
    spec=ModelSpec(name='Custom',source='csv',resolution='custom',period_minutes=15,target={'key':'level'})
    first=store.create(spec)
    store.add_frame(first,pd.DataFrame({'level':[1]},index=pd.DatetimeIndex(['2026-01-01T00:15:00Z'])))
    from app.graph import Graph
    changed=spec.model_copy(update={'period_minutes':30})
    graph=Graph.model_validate({'nodes':[{'id':'ml','kind':'ml','x':0,'y':0,'config':changed.model_dump()},{'id':'out','kind':'output','x':300,'y':0,'signal':changed.target.model_dump()}],'edges':[{'source':'ml','target':'out'}]})
    with pytest.raises(ValueError,match='ny modell'):
        store.save_graph(first,graph)
    assert store.spec(first).step_minutes==15


def test_csv_api_reduces_daily_values_to_weekly_model_period(tmp_path):
    with TestClient(create_app(tmp_path,HAClient(url='',token=''))) as client:
        spec=weekly()
        item=client.post('/api/models',json=spec.model_dump()).json()
        index=pd.date_range('2026-01-06T00:00:00Z',periods=7,freq='24h')
        frame=pd.DataFrame({'level':10,'rain':2,'last':5},index=index)
        frame.index.name='timestamp'
        result=client.post(f"/api/models/{item['id']}/csv",files={'file':('history.csv',frame.to_csv().encode(),'text/csv')},data={'interval_minutes':'1440'})
        assert result.status_code==200,result.text
        assert result.json()['rows']==1
        history=client.get(f"/api/models/{item['id']}/history").json()
        assert history==[{'timestamp':'2026-01-12T00:00:00+00:00','value':10.0}]
